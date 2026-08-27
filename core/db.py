import os, sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH=Path(os.getenv('DEFINITIVO_DB_PATH','data/definitivo.db'))

def connect():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB_PATH,timeout=30); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

def now_iso(): return datetime.now(timezone.utc).isoformat()

def init_db():
    c=connect()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS matches(
      id TEXT PRIMARY KEY, sport TEXT NOT NULL, competition TEXT, season TEXT, start_time TEXT,
      status TEXT, minute INTEGER, home_id INTEGER, home_name TEXT NOT NULL, home_short TEXT,
      away_id INTEGER, away_name TEXT NOT NULL, away_short TEXT, home_score INTEGER,
      away_score INTEGER, source TEXT, provider_match_id TEXT, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS match_stats(
      match_id TEXT NOT NULL, team_id INTEGER NOT NULL, metric TEXT NOT NULL, value REAL,
      source TEXT NOT NULL, observed_at TEXT NOT NULL,
      PRIMARY KEY(match_id,team_id,metric,source));
    CREATE TABLE IF NOT EXISTS players(id INTEGER PRIMARY KEY,team_id INTEGER,name TEXT NOT NULL,
      position TEXT,updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS player_stats(
      match_id TEXT NOT NULL,player_id INTEGER NOT NULL,metric TEXT NOT NULL,value REAL,
      source TEXT NOT NULL,observed_at TEXT NOT NULL,
      PRIMARY KEY(match_id,player_id,metric,source));
    CREATE TABLE IF NOT EXISTS diagnostics(id INTEGER PRIMARY KEY AUTOINCREMENT,match_id TEXT,source TEXT,
      stage TEXT NOT NULL,status TEXT NOT NULL,message TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_matches_start ON matches(start_time);
    CREATE INDEX IF NOT EXISTS idx_stats_team_metric ON match_stats(team_id,metric);
    CREATE INDEX IF NOT EXISTS idx_player_stats_player ON player_stats(player_id,metric);
    ''')
    c.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema','3')")
    c.commit(); c.close()
