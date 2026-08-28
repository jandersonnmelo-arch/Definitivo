import hashlib
import os
import re
import sqlite3
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("DEFINITIVO_DB_PATH", "data/definitivo.db"))
DB_TIMEOUT = int(os.getenv("DEFINITIVO_DB_TIMEOUT", "60"))
DB_BUSY_TIMEOUT_MS = int(os.getenv("DEFINITIVO_DB_BUSY_TIMEOUT_MS", "60000"))
_DB_WRITE_LOCK = threading.RLock()


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT, isolation_level="DEFERRED", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS}")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _norm(x):
    s = unicodedata.normalize("NFKD", str(x or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(cr|ec|sc|se|ca|fc|cf|ac)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def canonical_id(m):
    return hashlib.sha1("|".join([_norm(m.get("sport", "Futebol")), _norm(m.get("home_name")), _norm(m.get("away_name")), str(m.get("start_time") or "")[:16]]).encode()).hexdigest()[:20]


def canonical_player_id(source, provider_id):
    return int(hashlib.sha1(f"{source}:{provider_id}".encode()).hexdigest()[:15], 16)


def canonical_team_id(sport, name):
    return hashlib.sha1(f"{sport}:{_norm(name)}".encode()).hexdigest()[:18]


def _ensure_column(c, table, column, definition):
    cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    with _DB_WRITE_LOCK:
        c = connect()
        try:
            try:
                c.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                pass
            c.executescript("""
                CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS teams(
                    id TEXT PRIMARY KEY,sport TEXT NOT NULL,name TEXT NOT NULL,normalized_name TEXT NOT NULL,updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS team_sources(
                    team_id TEXT NOT NULL,source TEXT NOT NULL,provider_team_id TEXT NOT NULL,updated_at TEXT NOT NULL,
                    PRIMARY KEY(team_id,source),UNIQUE(source,provider_team_id)
                );
                CREATE TABLE IF NOT EXISTS matches(
                    id TEXT PRIMARY KEY,sport TEXT NOT NULL,competition TEXT,season TEXT,start_time TEXT,status TEXT,minute INTEGER,
                    home_id TEXT,home_name TEXT NOT NULL,home_short TEXT,away_id TEXT,away_name TEXT NOT NULL,away_short TEXT,
                    home_score INTEGER,away_score INTEGER,source TEXT,provider_match_id TEXT,updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS match_sources(
                    match_id TEXT NOT NULL,source TEXT NOT NULL,provider_match_id TEXT NOT NULL,updated_at TEXT NOT NULL,
                    PRIMARY KEY(match_id,source),UNIQUE(source,provider_match_id)
                );
                CREATE TABLE IF NOT EXISTS match_stats(
                    match_id TEXT NOT NULL,team_id TEXT NOT NULL,metric TEXT NOT NULL,value REAL,source TEXT NOT NULL,observed_at TEXT NOT NULL,
                    PRIMARY KEY(match_id,team_id,metric,source)
                );
                CREATE TABLE IF NOT EXISTS players(
                    id TEXT PRIMARY KEY,team_id TEXT,name TEXT NOT NULL,position TEXT,source TEXT NOT NULL,provider_player_id TEXT NOT NULL,updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS player_stats(
                    match_id TEXT NOT NULL,player_id TEXT NOT NULL,team_id TEXT,metric TEXT NOT NULL,value REAL,source TEXT NOT NULL,observed_at TEXT NOT NULL,
                    PRIMARY KEY(match_id,player_id,metric,source)
                );
                CREATE TABLE IF NOT EXISTS diagnostics(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,match_id TEXT,source TEXT,stage TEXT NOT NULL,status TEXT NOT NULL,message TEXT NOT NULL,created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_usage(
                    provider TEXT NOT NULL,day_utc TEXT NOT NULL,calls INTEGER NOT NULL DEFAULT 0,last_call TEXT,remaining_day INTEGER,remaining_minute INTEGER,
                    PRIMARY KEY(provider,day_utc)
                );
                CREATE TABLE IF NOT EXISTS api_call_log(id INTEGER PRIMARY KEY AUTOINCREMENT,provider TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_matches_start ON matches(start_time);
                CREATE INDEX IF NOT EXISTS idx_stats_team_metric ON match_stats(team_id,metric);
                CREATE INDEX IF NOT EXISTS idx_player_stats_player ON player_stats(player_id,metric);
                CREATE INDEX IF NOT EXISTS idx_player_stats_team ON player_stats(team_id,metric);
                CREATE INDEX IF NOT EXISTS idx_match_sources_provider ON match_sources(source,provider_match_id);
                CREATE INDEX IF NOT EXISTS idx_team_sources_provider ON team_sources(source,provider_team_id);
                CREATE INDEX IF NOT EXISTS idx_api_call_log_provider_time ON api_call_log(provider,created_at);
            """)
            _ensure_column(c, "players", "source", "TEXT")
            _ensure_column(c, "players", "provider_player_id", "TEXT")
            _ensure_column(c, "players", "updated_at", "TEXT")
            _ensure_column(c, "player_stats", "team_id", "TEXT")
            c.execute("UPDATE players SET source=COALESCE(source,'LEGACY'),provider_player_id=COALESCE(provider_player_id,CAST(id AS TEXT)),updated_at=COALESCE(updated_at,?)", (now_iso(),))
            c.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema','15')")
            c.commit()
        finally:
            c.close()


def _team_id(c, sport, name, source=None, provider_id=None):
    cid = canonical_team_id(sport, name)
    c.execute("""INSERT INTO teams(id,sport,name,normalized_name,updated_at) VALUES(?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET name=excluded.name,updated_at=excluded.updated_at""", (cid,sport,name,_norm(name),now_iso()))
    if source and provider_id is not None:
        c.execute("""INSERT INTO team_sources(team_id,source,provider_team_id,updated_at) VALUES(?,?,?,?)
            ON CONFLICT(team_id,source) DO UPDATE SET provider_team_id=excluded.provider_team_id,updated_at=excluded.updated_at""", (cid,source,str(provider_id),now_iso()))
    return cid


def record_api_usage(provider, remaining_day=None, remaining_minute=None):
    with _DB_WRITE_LOCK:
        c=connect()
        try:
            now=now_iso();day=datetime.now(timezone.utc).date().isoformat()
            c.execute("INSERT INTO api_call_log(provider,created_at) VALUES(?,?)",(provider,now))
            c.execute("""INSERT INTO api_usage(provider,day_utc,calls,last_call,remaining_day,remaining_minute) VALUES(?,?,?,?,?,?)
                ON CONFLICT(provider,day_utc) DO UPDATE SET calls=calls+1,last_call=excluded.last_call,
                remaining_day=COALESCE(excluded.remaining_day,api_usage.remaining_day),remaining_minute=COALESCE(excluded.remaining_minute,api_usage.remaining_minute)""",
                (provider,day,1,now,remaining_day,remaining_minute));c.commit()
        finally:c.close()


def usage_today(provider):
    c=connect()
    try:
        day=datetime.now(timezone.utc).date().isoformat();r=c.execute("SELECT * FROM api_usage WHERE provider=? AND day_utc=?",(provider,day)).fetchone()
        return dict(r) if r else {"provider":provider,"day_utc":day,"calls":0}
    finally:c.close()


def calls_last_minute(provider):
    c=connect()
    try:
        cutoff=(datetime.now(timezone.utc)-timedelta(seconds=60)).isoformat();return int(c.execute("SELECT COUNT(*) FROM api_call_log WHERE provider=? AND created_at>=?",(provider,cutoff)).fetchone()[0])
    finally:c.close()


def upsert_match(m):
    with _DB_WRITE_LOCK:
        last_error=None
        for attempt in range(3):
            c=connect()
            try:
                mid=m.get("id") or canonical_id(m);m["id"]=mid
                home_cid=_team_id(c,m.get("sport","Futebol"),m["home_name"],m.get("source"),m.get("home_id"));away_cid=_team_id(c,m.get("sport","Futebol"),m["away_name"],m.get("source"),m.get("away_id"));m["home_id"]=home_cid;m["away_id"]=away_cid
                old=c.execute("SELECT source FROM matches WHERE id=?",(mid,)).fetchone();source=m.get("source","unknown")
                if old and old["source"] and old["source"]!=source:source="multi"
                c.execute("""INSERT INTO matches(id,sport,competition,season,start_time,status,minute,home_id,home_name,home_short,away_id,away_name,away_short,home_score,away_score,source,provider_match_id,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET competition=COALESCE(excluded.competition,matches.competition),season=COALESCE(excluded.season,matches.season),start_time=COALESCE(excluded.start_time,matches.start_time),status=COALESCE(excluded.status,matches.status),minute=excluded.minute,home_id=excluded.home_id,home_name=excluded.home_name,home_short=COALESCE(excluded.home_short,matches.home_short),away_id=excluded.away_id,away_name=excluded.away_name,away_short=COALESCE(excluded.away_short,matches.away_short),home_score=excluded.home_score,away_score=excluded.away_score,source=excluded.source,provider_match_id=excluded.provider_match_id,updated_at=excluded.updated_at""",
                    (mid,m.get("sport","Futebol"),m.get("competition"),m.get("season"),m.get("start_time"),m.get("status"),m.get("minute"),home_cid,m["home_name"],m.get("home_short"),away_cid,m["away_name"],m.get("away_short"),m.get("home_score"),m.get("away_score"),source,str(m.get("provider_match_id",mid)),now_iso()))
                c.execute("""INSERT INTO match_sources(match_id,source,provider_match_id,updated_at) VALUES(?,?,?,?)
                    ON CONFLICT(match_id,source) DO UPDATE SET provider_match_id=excluded.provider_match_id,updated_at=excluded.updated_at""",(mid,m.get("source","unknown"),str(m.get("provider_match_id",mid)),now_iso()))
                c.commit();return mid
            except sqlite3.OperationalError as exc:
                c.rollback();last_error=exc
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():raise
                if attempt<2:time.sleep(.25*(attempt+1))
            finally:c.close()
        raise last_error


def get_provider_id(match_id,source):
    c=connect()
    try:
        r=c.execute("SELECT provider_match_id FROM match_sources WHERE match_id=? AND source=?",(match_id,source)).fetchone();return r["provider_match_id"] if r else None
    finally:c.close()


def get_team_provider_id(team_id,source):
    c=connect()
    try:
        r=c.execute("SELECT provider_team_id FROM team_sources WHERE team_id=? AND source=?",(team_id,source)).fetchone();return r["provider_team_id"] if r else None
    finally:c.close()


def _canonical_stat_team(c,match_id,source,provider_team_id,team_name):
    r=c.execute("SELECT team_id FROM team_sources WHERE source=? AND provider_team_id=?",(source,str(provider_team_id))).fetchone()
    if r:return r["team_id"]
    m=c.execute("SELECT sport FROM matches WHERE id=?",(match_id,)).fetchone()
    return _team_id(c,m["sport"] if m else "Futebol",team_name or str(provider_team_id),source,provider_team_id)


def upsert_match_stats(match_id,rows):
    if not rows:return
    with _DB_WRITE_LOCK:
        c=connect()
        try:
            for r in rows:
                if r.get("team_id") is None or r.get("value") is None:continue
                tid=_canonical_stat_team(c,match_id,r["source"],r["team_id"],r.get("team_name"))
                c.execute("""INSERT INTO match_stats(match_id,team_id,metric,value,source,observed_at) VALUES(?,?,?,?,?,?)
                    ON CONFLICT(match_id,team_id,metric,source) DO UPDATE SET value=excluded.value,observed_at=excluded.observed_at""",(match_id,tid,r["metric"],r["value"],r["source"],now_iso()))
            c.commit()
        finally:c.close()


def upsert_players(players):
    if not players:return
    with _DB_WRITE_LOCK:
        c=connect()
        try:
            for p in players:
                src=p.get("source","unknown");cid=canonical_player_id(src,p["id"]);team=p.get("team_id")
                team_cid=_canonical_stat_team(c,p.get("match_id",""),src,team,p.get("team_name")) if team is not None and p.get("match_id") else team
                c.execute("""INSERT INTO players(id,team_id,name,position,source,provider_player_id,updated_at) VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET team_id=excluded.team_id,name=excluded.name,position=excluded.position,updated_at=excluded.updated_at""",
                    (cid,team_cid,p["name"],p.get("position"),src,str(p["id"]),now_iso()))
            c.commit()
        finally:c.close()


def upsert_player_stats(match_id,rows):
    if not rows:return
    with _DB_WRITE_LOCK:
        c=connect()
        try:
            for r in rows:
                if r.get("value") is None:continue
                src=r.get("source","unknown");cid=canonical_player_id(src,r["player_id"])
                raw_team=r.get("team_id")
                team_cid=_canonical_stat_team(c,match_id,src,raw_team,r.get("team_name")) if raw_team is not None else None
                c.execute("""INSERT INTO player_stats(match_id,player_id,team_id,metric,value,source,observed_at) VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(match_id,player_id,metric,source) DO UPDATE SET team_id=excluded.team_id,value=excluded.value,observed_at=excluded.observed_at""",
                    (match_id,cid,team_cid,r["metric"],r["value"],src,now_iso()))
            c.commit()
        finally:c.close()


def add_diagnostic(stage,status,message,source=None,match_id=None):
    with _DB_WRITE_LOCK:
        c=connect()
        try:c.execute("INSERT INTO diagnostics(match_id,source,stage,status,message,created_at) VALUES(?,?,?,?,?,?)",(match_id,source,stage,status,message,now_iso()));c.commit()
        finally:c.close()


def get_matches(sport="Futebol",limit=100):
    c=connect()
    try:
        rows=c.execute("SELECT * FROM matches WHERE sport=? ORDER BY CASE status WHEN 'LIVE' THEN 0 WHEN 'PAUSED' THEN 0 ELSE 1 END,start_time LIMIT ?",(sport,limit)).fetchall();return [dict(r) for r in rows]
    finally:c.close()


def get_match(mid):
    c=connect()
    try:r=c.execute("SELECT * FROM matches WHERE id=?",(mid,)).fetchone();return dict(r) if r else None
    finally:c.close()


def get_stats(mid):
    c=connect()
    try:rows=c.execute("SELECT * FROM match_stats WHERE match_id=? ORDER BY metric,team_id,source",(mid,)).fetchall();return [dict(x) for x in rows]
    finally:c.close()


def get_players(mid):
    c=connect()
    try:
        m=c.execute("SELECT home_id,away_id FROM matches WHERE id=?",(mid,)).fetchone()
        if not m:return []
        allowed={str(x) for x in (m["home_id"],m["away_id"]) if x}
        if not allowed:return []
        rows=c.execute("""SELECT p.id,p.team_id,p.name,p.position,ps.metric,ps.value,ps.source
            FROM players p JOIN player_stats ps ON ps.player_id=p.id
            WHERE ps.match_id=? AND ps.team_id IN (?,?) ORDER BY ps.team_id,p.name,ps.metric""",
            (mid,m["home_id"],m["away_id"])).fetchall();return [dict(x) for x in rows]
    finally:c.close()


def get_diagnostics(limit=100):
    c=connect()
    try:rows=c.execute("SELECT * FROM diagnostics ORDER BY id DESC LIMIT ?",(limit,)).fetchall();return [dict(x) for x in rows]
    finally:c.close()


def team_history(team_id,before_iso=None,limit=10):
    c=connect()
    try:
        sql="SELECT * FROM matches WHERE sport='Futebol' AND status='FINISHED' AND (home_id=? OR away_id=?)";p=[team_id,team_id]
        if before_iso:sql+=" AND start_time < ?";p.append(before_iso)
        sql+=" ORDER BY start_time DESC LIMIT ?";p.append(limit);return [dict(x) for x in c.execute(sql,p).fetchall()]
    finally:c.close()


def metric_history(team_id,metric,before_iso=None,limit=10):
    c=connect()
    try:
        sql="SELECT m.start_time,s.value FROM match_stats s JOIN matches m ON m.id=s.match_id WHERE s.team_id=? AND s.metric=? AND m.status='FINISHED'";p=[team_id,metric]
        if before_iso:sql+=" AND m.start_time < ?";p.append(before_iso)
        sql+=" ORDER BY m.start_time DESC LIMIT ?";p.append(limit);return [dict(x) for x in c.execute(sql,p).fetchall()]
    finally:c.close()


def player_history(player_id,before_iso=None,limit=20):
    c=connect()
    try:
        sql="SELECT ps.match_id,ps.metric,ps.value,ps.source,m.start_time,m.home_name,m.away_name FROM player_stats ps JOIN matches m ON m.id=ps.match_id WHERE ps.player_id=? AND m.status='FINISHED'";p=[player_id]
        if before_iso:sql+=" AND m.start_time < ?";p.append(before_iso)
        sql+=" ORDER BY m.start_time DESC LIMIT ?";p.append(limit);return [dict(x) for x in c.execute(sql,p).fetchall()]
    finally:c.close()


def player_history_summary(team_id,before_iso=None,limit=20):
    c=connect()
    try:
        sql="""
            SELECT p.id,p.name,p.position,
              COUNT(DISTINCT ps.match_id) matches,
              SUM(CASE WHEN ps.metric='goals' THEN ps.value ELSE 0 END) goals,
              SUM(CASE WHEN ps.metric='assists' THEN ps.value ELSE 0 END) assists,
              SUM(CASE WHEN ps.metric='passes_completed' THEN ps.value ELSE 0 END) passes_completed,
              SUM(CASE WHEN ps.metric='tackles' THEN ps.value ELSE 0 END) tackles,
              SUM(CASE WHEN ps.metric='fouls' THEN ps.value ELSE 0 END) fouls,
              SUM(CASE WHEN ps.metric='was_fouled' THEN ps.value ELSE 0 END) was_fouled,
              SUM(CASE WHEN ps.metric='shots_on_target' THEN ps.value ELSE 0 END) shots_on_target,
              SUM(CASE WHEN ps.metric='shots' THEN ps.value ELSE 0 END) shots
            FROM players p JOIN player_stats ps ON ps.player_id=p.id JOIN matches m ON m.id=ps.match_id
            WHERE ps.team_id=? AND m.status='FINISHED'
        """;p=[team_id]
        if before_iso:sql+=" AND m.start_time < ?";p.append(before_iso)
        sql+=" GROUP BY p.id,p.name,p.position ORDER BY matches DESC,p.name LIMIT ?";p.append(limit)
        return [dict(x) for x in c.execute(sql,p).fetchall()]
    finally:c.close()


def history_coverage(team_id,before_iso=None):
    c=connect()
    try:
        sql="SELECT COUNT(*) FROM matches WHERE sport='Futebol' AND status='FINISHED' AND (home_id=? OR away_id=?)";p=[team_id,team_id]
        if before_iso:sql+=" AND start_time < ?";p.append(before_iso)
        return int(c.execute(sql,p).fetchone()[0])
    finally:c.close()
