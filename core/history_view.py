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


def _name_team_ids(c,team_name):
    """Encontra todas as identidades canônicas que representam a equipe."""
    if not team_name:
        return set()
    ids=set()
    try:
        rows=c.execute("SELECT id,name,normalized_name FROM teams WHERE sport='Futebol'").fetchall()
        for r in rows:
            if _same(team_name,r['name']) or _same(team_name,r['normalized_name']):
                ids.add(r['id'])
    except Exception:
        pass
    return ids


def team_history_for_view(team_id,team_name,before_iso,limit=10):
    """Recupera os últimos jogos históricos persistidos da equipe.

    A análise pode ter dados consolidados a partir de ESPN/FotMob enquanto os
    jogos históricos permanecem associados a outra identidade canônica por causa
    de nomes diferentes. A visualização resolve isso por ID, por todas as
    identidades equivalentes na tabela teams e, por último, pelo nome persistido
    diretamente em matches.
    """
    if not team_id and not team_name:
        return []

    c=connect()
    try:
        candidates={}

        # 1) Consulta oficial por ID.
        if team_id:
            try:
                for row in team_history(team_id,before_iso,limit):
                    candidates[row.get('id')]=row
            except Exception:
                pass

        # 2) Todas as identidades da equipe encontradas por nome/alias.
        team_ids={team_id} if team_id else set()
        team_ids.update(_name_team_ids(c,team_name))
        if team_ids:
            placeholders=','.join('?' for _ in team_ids)
            sql=f"SELECT * FROM matches WHERE sport='Futebol' AND (home_id IN ({placeholders}) OR away_id IN ({placeholders}))"
            params=list(team_ids)+list(team_ids)
            if before_iso:
                sql+=' AND start_time<?';params.append(before_iso)
            sql+=' ORDER BY start_time DESC'
            for r in c.execute(sql,params).fetchall():
                item=dict(r)
                if _finished_match(item):
                    candidates[item.get('id')]=item

        # 3) Fallback por nome gravado na própria partida. Não existe LIMIT
        # antes do filtro da equipe.
        sql="SELECT * FROM matches WHERE sport='Futebol'"
        params=[]
        if before_iso:
            sql+=' AND start_time<?';params.append(before_iso)
        sql+=' ORDER BY start_time DESC'
        for r in c.execute(sql,params).fetchall():
            item=dict(r)
            if not _finished_match(item):
                continue
            if _same(team_name,item.get('home_name')) or _same(team_name,item.get('away_name')):
                candidates[item.get('id')]=item
                if len(candidates)>=limit:
                    break

        return sorted(candidates.values(),key=lambda x:x.get('start_time') or '',reverse=True)[:limit]
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
