import hashlib
from .db import connect, now_iso

def canonical_id(source, provider_id):
    return hashlib.sha1(f'{source}:{provider_id}'.encode()).hexdigest()[:16]

def upsert_match(m):
    c=connect()
    c.execute('''INSERT INTO matches(id,sport,competition,season,start_time,status,minute,home_id,home_name,home_short,away_id,away_name,away_short,home_score,away_score,source,provider_match_id,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
      competition=excluded.competition,season=excluded.season,start_time=excluded.start_time,status=excluded.status,minute=excluded.minute,
      home_id=excluded.home_id,home_name=excluded.home_name,home_short=excluded.home_short,away_id=excluded.away_id,away_name=excluded.away_name,
      away_short=excluded.away_short,home_score=excluded.home_score,away_score=excluded.away_score,source=excluded.source,provider_match_id=excluded.provider_match_id,updated_at=excluded.updated_at''',
      (m['id'],m.get('sport','Futebol'),m.get('competition'),m.get('season'),m.get('start_time'),m.get('status'),m.get('minute'),m.get('home_id'),m['home_name'],m.get('home_short'),m.get('away_id'),m['away_name'],m.get('away_short'),m.get('home_score'),m.get('away_score'),m.get('source','unknown'),str(m.get('provider_match_id',m['id'])),now_iso()))
    c.commit(); c.close()

def upsert_match_stats(match_id,rows):
    if not rows:return
    c=connect()
    for r in rows:
        if r.get('team_id') is None or r.get('value') is None: continue
        c.execute('''INSERT INTO match_stats(match_id,team_id,metric,value,source,observed_at) VALUES(?,?,?,?,?,?)
        ON CONFLICT(match_id,team_id,metric,source) DO UPDATE SET value=excluded.value,observed_at=excluded.observed_at''',(match_id,r['team_id'],r['metric'],r['value'],r['source'],now_iso()))
    c.commit(); c.close()

def upsert_players(players):
    if not players:return
    c=connect()
    for p in players:
        c.execute('''INSERT INTO players(id,team_id,name,position,updated_at) VALUES(?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET team_id=excluded.team_id,name=excluded.name,position=excluded.position,updated_at=excluded.updated_at''',(p['id'],p.get('team_id'),p['name'],p.get('position'),now_iso()))
    c.commit(); c.close()

def upsert_player_stats(match_id,rows):
    if not rows:return
    c=connect()
    for r in rows:
        if r.get('value') is None: continue
        c.execute('''INSERT INTO player_stats(match_id,player_id,metric,value,source,observed_at) VALUES(?,?,?,?,?,?)
        ON CONFLICT(match_id,player_id,metric,source) DO UPDATE SET value=excluded.value,observed_at=excluded.observed_at''',(match_id,r['player_id'],r['metric'],r['value'],r['source'],now_iso()))
    c.commit(); c.close()

def add_diagnostic(stage,status,message,source=None,match_id=None):
    c=connect(); c.execute('INSERT INTO diagnostics(match_id,source,stage,status,message,created_at) VALUES(?,?,?,?,?,?)',(match_id,source,stage,status,message,now_iso())); c.commit(); c.close()

def get_matches(sport='Futebol',limit=100):
    c=connect(); rows=c.execute("SELECT * FROM matches WHERE sport=? ORDER BY CASE status WHEN 'LIVE' THEN 0 WHEN 'PAUSED' THEN 0 ELSE 1 END,start_time LIMIT ?",(sport,limit)).fetchall(); c.close(); return [dict(r) for r in rows]

def get_match(mid):
    c=connect(); r=c.execute('SELECT * FROM matches WHERE id=?',(mid,)).fetchone(); c.close(); return dict(r) if r else None

def get_stats(mid):
    c=connect(); r=c.execute('SELECT * FROM match_stats WHERE match_id=? ORDER BY metric,team_id,source',(mid,)).fetchall(); c.close(); return [dict(x) for x in r]

def get_players(mid):
    c=connect(); r=c.execute('''SELECT p.id,p.team_id,p.name,p.position,ps.metric,ps.value,ps.source FROM players p JOIN player_stats ps ON ps.player_id=p.id WHERE ps.match_id=? ORDER BY p.team_id,p.name,ps.metric''',(mid,)).fetchall(); c.close(); return [dict(x) for x in r]

def get_diagnostics(limit=100):
    c=connect(); r=c.execute('SELECT * FROM diagnostics ORDER BY id DESC LIMIT ?',(limit,)).fetchall(); c.close(); return [dict(x) for x in r]

def team_history(team_id,before_iso=None,limit=10):
    c=connect(); sql="SELECT * FROM matches WHERE sport='Futebol' AND status='FINISHED' AND (home_id=? OR away_id=?)"; p=[team_id,team_id]
    if before_iso: sql+=' AND start_time < ?'; p.append(before_iso)
    sql+=' ORDER BY start_time DESC LIMIT ?'; p.append(limit); rows=c.execute(sql,p).fetchall(); c.close(); return [dict(x) for x in rows]

def metric_history(team_id,metric,before_iso=None,limit=10):
    c=connect(); sql="SELECT m.start_time,s.value FROM match_stats s JOIN matches m ON m.id=s.match_id WHERE s.team_id=? AND s.metric=? AND m.status='FINISHED'"; p=[team_id,metric]
    if before_iso: sql+=' AND m.start_time < ?'; p.append(before_iso)
    sql+=' ORDER BY m.start_time DESC LIMIT ?'; p.append(limit); rows=c.execute(sql,p).fetchall(); c.close(); return [dict(x) for x in rows]
