import re
import unicodedata
from datetime import datetime
SOURCE_PRIORITY={'ESPN':0,'FotMob':1,'API-Futebol':2,'API-Football':3,'Football-Data.org':4,'LEGACY':99}
ALIASES={'goias':'goias','goias ec':'goias','goias esporte clube':'goias','nautico':'nautico','nautico pe':'nautico','clube nautico capibaribe':'nautico','athletic':'athletic','athletic club':'athletic','athletic club mg':'athletic','novorizontino':'novorizontino','gremio novorizontino':'novorizontino','sport':'sport recife','sport recife':'sport recife','sport club do recife':'sport recife'}
def _norm(value):
    s=unicodedata.normalize('NFKD',str(value or '')).encode('ascii','ignore').decode().lower();s=re.sub(r'[^a-z0-9]+',' ',s).strip()
    if s in ALIASES:return ALIASES[s]
    s=re.sub(r'\b(fc|cf|sc|ec|ac|se|ca|cr|club|clube|football|futbol|esporte|esporte clube)\b',' ',s);s=re.sub(r'[^a-z0-9]+',' ',s).strip();return ALIASES.get(s,s)
def _dt(value):
    try:return datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except Exception:return None
def _is_serie_b(row):return 'serie b' in str(row.get('competition') or '').lower() or 'série b' in str(row.get('competition') or '').lower()
def _same_match(a,b):
    if not (_is_serie_b(a) and _is_serie_b(b)):return False
    if _norm(a.get('home_name'))!=_norm(b.get('home_name')) or _norm(a.get('away_name'))!=_norm(b.get('away_name')):return False
    da,db=_dt(a.get('start_time')), _dt(b.get('start_time'))
    return bool(da and db and abs((da-db).total_seconds())<=6*3600)
def _rank(row):return SOURCE_PRIORITY.get(str(row.get('source') or ''),50)

def reconcile_serie_b_matches():
    from core.db import connect,now_iso
    c=connect();rows=[dict(r) for r in c.execute("SELECT * FROM matches WHERE sport='Futebol' AND (lower(competition) LIKE '%serie b%' OR lower(competition) LIKE '%série b%') ORDER BY start_time,id").fetchall()];groups=[];used=set()
    for row in rows:
        if row['id'] in used:continue
        group=[row];used.add(row['id'])
        for other in rows:
            if other['id'] in used:continue
            if _same_match(row,other):group.append(other);used.add(other['id'])
        groups.append(group)
    merged=sources_moved=stats_moved=players_moved=0
    for group in groups:
        if len(group)<2:continue
        group.sort(key=lambda r:(_rank(r),0 if r.get('home_score') is not None and r.get('away_score') is not None else 1,r['id']));canonical=group[0];cid=canonical['id']
        scored=[r for r in group if r.get('home_score') is not None and r.get('away_score') is not None]
        if scored:
            best_score=min(scored,key=lambda r:(_rank(r),r['id']))
            if _rank(best_score)<=_rank(canonical)+1:canonical=best_score;cid=canonical['id']
        for dup in group:
            did=dup['id']
            if did==cid:continue
            c.execute("""UPDATE matches SET competition=COALESCE(competition,?),season=COALESCE(season,?),start_time=COALESCE(start_time,?),status=CASE WHEN status IS NULL OR status='' THEN ? ELSE status END,home_score=COALESCE(home_score,?),away_score=COALESCE(away_score,?),home_short=COALESCE(home_short,?),away_short=COALESCE(away_short,?),source=CASE WHEN source=? THEN ? ELSE 'multi' END,updated_at=? WHERE id=?""",(dup.get('competition'),dup.get('season'),dup.get('start_time'),dup.get('status'),dup.get('home_score'),dup.get('away_score'),dup.get('home_short'),dup.get('away_short'),canonical.get('source'),dup.get('source'),now_iso(),cid))
            for ms in c.execute('SELECT source,provider_match_id,updated_at FROM match_sources WHERE match_id=?',(did,)).fetchall():
                try:c.execute('INSERT INTO match_sources(match_id,source,provider_match_id,updated_at) VALUES(?,?,?,?)',(cid,ms['source'],ms['provider_match_id'],ms['updated_at']));sources_moved+=1
                except Exception:pass
            for st in c.execute('SELECT team_id,metric,value,source,observed_at FROM match_stats WHERE match_id=?',(did,)).fetchall():
                try:c.execute('INSERT INTO match_stats(match_id,team_id,metric,value,source,observed_at) VALUES(?,?,?,?,?,?)',(cid,st['team_id'],st['metric'],st['value'],st['source'],st['observed_at']));stats_moved+=1
                except Exception:pass
            # team_id é obrigatório para preservar a separação dos jogadores das duas equipes.
            for ps in c.execute('SELECT player_id,team_id,metric,value,source,observed_at FROM player_stats WHERE match_id=?',(did,)).fetchall():
                try:c.execute('INSERT INTO player_stats(match_id,player_id,team_id,metric,value,source,observed_at) VALUES(?,?,?,?,?,?,?)',(cid,ps['player_id'],ps['team_id'],ps['metric'],ps['value'],ps['source'],ps['observed_at']));players_moved+=1
                except Exception:pass
            c.execute('DELETE FROM match_stats WHERE match_id=?',(did,));c.execute('DELETE FROM player_stats WHERE match_id=?',(did,));c.execute('DELETE FROM match_sources WHERE match_id=?',(did,));c.execute('DELETE FROM matches WHERE id=?',(did,));merged+=1
    c.commit();c.close();return {'matches_merged':merged,'sources_moved':sources_moved,'stats_moved':stats_moved,'player_stats_moved':players_moved}
