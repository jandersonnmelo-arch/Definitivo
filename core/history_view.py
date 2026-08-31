import re
import unicodedata
from datetime import datetime, timezone
from core.db import connect, player_history_summary, team_history

TEAM_ALIASES={'rayo vallecano de madrid':'rayo vallecano','rayo vallecano':'rayo vallecano','fc barcelona':'barcelona','barcelona':'barcelona'}

def _norm(value):
    s=unicodedata.normalize('NFKD',str(value or '')).encode('ascii','ignore').decode().lower()
    s=re.sub(r'\b(cr|ec|sc|se|ca|fc|cf|ac|club|clube|football|futbol)\b',' ',s)
    s=re.sub(r'[^a-z0-9]+',' ',s).strip();return TEAM_ALIASES.get(s,s)

def _same(a,b):
    a,b=_norm(a),_norm(b)
    if not a or not b:return False
    if a==b or a in b or b in a:return True
    ta,tb=set(a.split()),set(b.split());common=ta&tb
    return len(common)>=2 and len(common)>=min(len(ta),len(tb))

def _parse_dt(value):
    if not value:return None
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:return None

def _finished_match(item):
    status=str(item.get('status') or '').strip().upper()
    if status in {'FINISHED','FT','FINAL','FINALIZADO','AET','PEN','POSTGAME','STATUS_FINAL'}:return True
    return item.get('home_score') is not None and item.get('away_score') is not None

def _name_team_ids(c,team_name):
    if not team_name:return set()
    ids=set()
    try:
        for r in c.execute("SELECT id,name,normalized_name FROM teams WHERE sport='Futebol'").fetchall():
            if _same(team_name,r['name']) or _same(team_name,r['normalized_name']):ids.add(r['id'])
    except Exception:pass
    return ids

def team_history_for_view(team_id,team_name,before_iso,limit=10):
    """Recupera histórico por ID, nome da partida e identidade das estatísticas."""
    if not team_id and not team_name:return []
    c=connect()
    try:
        candidates={};before=_parse_dt(before_iso)
        if team_id:
            try:
                for row in team_history(team_id,before_iso,limit):
                    item=dict(row);dt=_parse_dt(item.get('start_time'))
                    if _finished_match(item) and (not before or (dt and dt<before)):candidates[item.get('id')]=item
            except Exception:pass
        team_ids={team_id} if team_id else set();team_ids.update(_name_team_ids(c,team_name))
        if team_ids:
            ph=','.join('?' for _ in team_ids);sql=f"SELECT * FROM matches WHERE sport='Futebol' AND (home_id IN ({ph}) OR away_id IN ({ph}))";params=list(team_ids)+list(team_ids)
            for r in c.execute(sql,params).fetchall():
                item=dict(r);dt=_parse_dt(item.get('start_time'))
                if _finished_match(item) and (not before or (dt and dt<before)):candidates[item.get('id')]=item
        for r in c.execute("SELECT * FROM matches WHERE sport='Futebol'").fetchall():
            item=dict(r);dt=_parse_dt(item.get('start_time'))
            if not _finished_match(item) or (before and (not dt or dt>=before)):continue
            if _same(team_name,item.get('home_name')) or _same(team_name,item.get('away_name')):candidates[item.get('id')]=item
        # Importante: o motor já encontra os dados históricos pela identidade
        # das estatísticas. Reutilizamos essa mesma identidade para a tela.
        if team_name:
            q="""SELECT DISTINCT m.* FROM matches m JOIN match_stats s ON s.match_id=m.id LEFT JOIN teams t ON t.id=s.team_id WHERE m.sport='Futebol' AND m.status='FINISHED'"""
            for r in c.execute(q).fetchall():
                item=dict(r);dt=_parse_dt(item.get('start_time'))
                if before and (not dt or dt>=before):continue
                stat_names=[x['name'] for x in c.execute("SELECT DISTINCT t.name FROM match_stats s LEFT JOIN teams t ON t.id=s.team_id WHERE s.match_id=?",(item.get('id'),)).fetchall() if x['name']]
                if any(_same(team_name,n) for n in stat_names):candidates[item.get('id')]=item
        def key(item):return _parse_dt(item.get('start_time')) or datetime.min.replace(tzinfo=timezone.utc)
        return sorted(candidates.values(),key=key,reverse=True)[:limit]
    finally:c.close()

def player_history_for_view(team_id,team_name,before_iso,limit=20):
    result=player_history_summary(team_id,before_iso=before_iso,limit=limit) if team_id else []
    if result or not team_name:return result
    c=connect()
    try:ids=[r['id'] for r in c.execute("SELECT id,name FROM teams WHERE sport='Futebol'").fetchall() if _same(team_name,r['name'])]
    finally:c.close()
    merged=[];seen=set()
    for tid in ids:
        for row in player_history_summary(tid,before_iso=before_iso,limit=limit):
            key=(row.get('name'),row.get('team_id'))
            if key not in seen:merged.append(row);seen.add(key)
    return merged[:limit]
