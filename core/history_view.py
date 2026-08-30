import re
import unicodedata
from core.db import connect, player_history_summary


def _norm(value):
    s=unicodedata.normalize('NFKD',str(value or '')).encode('ascii','ignore').decode().lower()
    s=re.sub(r'\b(cr|ec|sc|se|ca|fc|cf|ac|club|clube|football|futbol)\b',' ',s)
    return re.sub(r'[^a-z0-9]+',' ',s).strip()


def _same(a,b):
    a,b=_norm(a),_norm(b)
    return bool(a and b and (a==b or a in b or b in a))


def team_history_for_view(team_id,team_name,before_iso,limit=10):
    """Histórico visual por identidade da equipe, com fallback seguro pelo nome.

    O fallback é somente de leitura: não cria partidas nem chama qualquer API.
    Isso recupera históricos gravados com IDs de provedores diferentes após a
    normalização/reconciliação das equipes.
    """
    if not team_name:
        return []
    c=connect()
    try:
        sql="SELECT * FROM matches WHERE status='FINISHED'"
        params=[]
        if before_iso:
            sql+=" AND start_time<?";params.append(before_iso)
        sql+=" ORDER BY start_time DESC LIMIT ?";params.append(max(limit*8,limit))
        rows=[]
        for r in c.execute(sql,params).fetchall():
            item=dict(r)
            if team_id and (item.get('home_id')==team_id or item.get('away_id')==team_id):
                rows.append(item)
            elif _same(team_name,item.get('home_name')) or _same(team_name,item.get('away_name')):
                rows.append(item)
            if len(rows)>=limit:break
        return rows
    finally:c.close()


def player_history_for_view(team_id,team_name,before_iso,limit=20):
    """Mantém a consulta individual pelo ID canônico e tenta IDs encontrados por nome."""
    result=player_history_summary(team_id,before_iso=before_iso,limit=limit) if team_id else []
    if result or not team_name:
        return result
    c=connect()
    try:
        rows=c.execute("SELECT id,name FROM teams WHERE sport='Futebol'").fetchall()
        ids=[r['id'] for r in rows if _same(team_name,r['name'])]
    finally:c.close()
    merged=[];seen=set()
    for tid in ids:
        for row in player_history_summary(tid,before_iso=before_iso,limit=limit):
            key=(row.get('name'),row.get('team_id'))
            if key not in seen:merged.append(row);seen.add(key)
    return merged[:limit]
