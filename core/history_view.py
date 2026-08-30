import re
import unicodedata
from core.db import connect, player_history_summary, team_history


def _norm(value):
    s=unicodedata.normalize('NFKD',str(value or '')).encode('ascii','ignore').decode().lower()
    s=re.sub(r'\b(cr|ec|sc|se|ca|fc|cf|ac|club|clube|football|futbol)\b',' ',s)
    return re.sub(r'[^a-z0-9]+',' ',s).strip()


def _same(a,b):
    a,b=_norm(a),_norm(b)
    return bool(a and b and (a==b or a in b or b in a))


def _finished_match(item):
    status=str(item.get('status') or '').strip().upper()
    if status in {'FINISHED','FT','FINAL','FINALIZADO','AET','PEN','POSTGAME'}:
        return True
    return item.get('home_score') is not None and item.get('away_score') is not None


def team_history_for_view(team_id,team_name,before_iso,limit=10):
    """Usa exatamente a mesma fonte de histórico do motor de análise.

    Isso evita que a análise encontre 10 jogos enquanto a visualização encontre 0.
    A primeira consulta é a função oficial team_history() do banco. Se o ID
    canônico não resolver, fazemos um fallback somente de leitura por nome.
    Nenhuma API é chamada aqui.
    """
    if not team_id and not team_name:
        return []

    # Caminho principal: exatamente a consulta que já alimenta o motor.
    if team_id:
        try:
            rows=team_history(team_id,before_iso,limit)
            if rows:
                return rows[:limit]
        except Exception:
            pass

    # Fallback legado por nome, somente leitura.
    if not team_name:
        return []

    c=connect()
    try:
        sql="SELECT * FROM matches"
        params=[]
        if before_iso:
            sql+=" WHERE start_time<?"
            params.append(before_iso)
        sql+=" ORDER BY start_time DESC LIMIT ?"
        params.append(max(limit*50,limit))
        rows=[]
        for r in c.execute(sql,params).fetchall():
            item=dict(r)
            if not _finished_match(item):
                continue
            if _same(team_name,item.get('home_name')) or _same(team_name,item.get('away_name')):
                rows.append(item)
                if len(rows)>=limit:
                    break
        return rows
    finally:
        c.close()


def player_history_for_view(team_id,team_name,before_iso,limit=20):
    result=player_history_summary(team_id,before_iso=before_iso,limit=limit) if team_id else []
    if result or not team_name:
        return result
    c=connect()
    try:
        rows=c.execute("SELECT id,name FROM teams WHERE sport='Futebol'").fetchall()
        ids=[r['id'] for r in rows if _same(team_name,r['name'])]
    finally:
        c.close()
    merged=[];seen=set()
    for tid in ids:
        for row in player_history_summary(tid,before_iso=before_iso,limit=limit):
            key=(row.get('name'),row.get('team_id'))
            if key not in seen:
                merged.append(row);seen.add(key)
    return merged[:limit]
