import re
import unicodedata
from core.db import connect, player_history_summary, team_history


TEAM_ALIASES={
    'rayo vallecano de madrid':'rayo vallecano',
    'rayo vallecano':'rayo vallecano',
    'fc barcelona':'barcelona',
    'barcelona':'barcelona',
}


def _norm(value):
    s=unicodedata.normalize('NFKD',str(value or '')).encode('ascii','ignore').decode().lower()
    s=re.sub(r'\b(cr|ec|sc|se|ca|fc|cf|ac|club|clube|football|futbol)\b',' ',s)
    s=re.sub(r'[^a-z0-9]+',' ',s).strip()
    return TEAM_ALIASES.get(s,s)


def _same(a,b):
    a,b=_norm(a),_norm(b)
    return bool(a and b and (a==b or a in b or b in a))


def _finished_match(item):
    status=str(item.get('status') or '').strip().upper()
    if status in {'FINISHED','FT','FINAL','FINALIZADO','AET','PEN','POSTGAME'}:
        return True
    return item.get('home_score') is not None and item.get('away_score') is not None


def team_history_for_view(team_id,team_name,before_iso,limit=10):
    """Recupera o histórico persistido sem depender exclusivamente do ID canônico.

    A análise já usa os mesmos registros para calcular as médias. A visualização
    deve encontrar esses registros mesmo quando o provedor mudou o nome/ID da
    equipe. O filtro por nome é feito depois de buscar todos os jogos elegíveis,
    evitando que um LIMIT global esconda o histórico de uma equipe que joga em
    uma competição com muitos eventos recentes.
    """
    if not team_id and not team_name:
        return []

    c=connect()
    try:
        # 1) Caminho por identidade canônica. Mantemos como primeira tentativa.
        if team_id:
            try:
                rows=team_history(team_id,before_iso,limit)
                if rows:
                    return rows[:limit]
            except Exception:
                pass

        # 2) Busca ampla no banco e resolução por nome normalizado/alias.
        # Não usamos LIMIT antes de identificar a equipe: isso era capaz de
        # retornar 0 mesmo existindo histórico persistido mais antigo.
        sql="SELECT * FROM matches WHERE sport='Futebol'"
        params=[]
        if before_iso:
            sql+=" AND start_time<?"
            params.append(before_iso)
        sql+=" ORDER BY start_time DESC"
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
