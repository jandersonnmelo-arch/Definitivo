from .db import connect

def get_dashboard_matches(sport='Todos'):
    c=connect()
    if sport and sport!='Todos':
        sport=sport.replace('⚽ ','').replace('🏀 ','').replace('🏐 ',''); rows=c.execute('SELECT * FROM matches WHERE sport=? ORDER BY start_time',(sport,)).fetchall()
    else: rows=c.execute("SELECT * FROM matches ORDER BY CASE status WHEN 'LIVE' THEN 0 ELSE 1 END,start_time").fetchall()
    c.close(); return [dict(r) for r in rows]
def get_match(mid):
    c=connect(); r=c.execute('SELECT * FROM matches WHERE id=?',(mid,)).fetchone(); c.close(); return dict(r) if r else None
def get_match_stats(mid):
    c=connect(); r=c.execute('SELECT * FROM match_stats WHERE match_id=? ORDER BY metric,team_id',(mid,)).fetchall(); c.close(); return [dict(x) for x in r]
def get_match_players(mid):
    c=connect(); r=c.execute('SELECT p.id,p.team_id,p.name,p.position,ps.metric,ps.value FROM players p JOIN player_stats ps ON ps.player_id=p.id WHERE ps.match_id=? ORDER BY p.team_id,p.name,ps.metric',(mid,)).fetchall(); c.close(); return [dict(x) for x in r]
