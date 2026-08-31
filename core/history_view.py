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
    if not a or not b:return False
    if a==b or a in b or b in a:return True
    ta,tb=set(a.split()),set(b.split());common=ta & tb
    return len(common)>=2 and len(common)>=min(len(ta),len(tb))


def _finished_match(item):
    status=str(item.get('status') or '').strip().upper()
    if status in {'FINISHED','FT','FINAL','FINALIZADO','AET','PEN','POSTGAME','STATUS_FINAL'}:
        return True
    return item.get('home_score') is not None and item.get('away_score') is not None


def _name_team_ids(c,team_name):
    if not team_name:return set()
    ids=set()
    try:
        rows=c.execute("SELECT id,name,normalized_name FROM teams WHERE sport='Futebol'").fetchall()
        for r in rows:
            if _same(team_name,r['name']) or _same(team_name,r['normalized_name']):ids.add(r['id'])
    except Exception:pass
    return ids


def team_history_for_view(team_id,team_name,before_iso,limit=10):
    """Mostra os mesmos jogos FINISHED usados pelo motor estatístico.

    Não depende apenas do ID canônico. O histórico pode ter sido persistido por
    ESPN/FotMob com outra identidade da equipe; por isso usamos ID, identidades
    equivalentes e, por fim, o nome gravado na própria partida. O filtro de data
    permanece textual como no motor, evitando eliminar registros com formatos de
    timestamp diferentes.
    """
    if not team_id and not team_name:return []
    c=connect()
    try:
        candidates={}

        # 1) Caminho oficial do banco.
        if team_id:
            try:
                for row in team_history(team_id,before_iso,limit):
                    if _finished_match(row):candidates[row.get('id')]=row
            except Exception:pass

        # 2) Todas as identidades equivalentes da equipe.
        team_ids={team_id} if team_id else set()
        team_ids.update(_name_team_ids(c,team_name))
        if team_ids:
            placeholders=','.join('?' for _ in team_ids)
            sql=f"SELECT * FROM matches WHERE sport='Futebol' AND status='FINISHED' AND start_time<? AND (home_id IN ({placeholders}) OR away_id IN ({placeholders})) ORDER BY start_time DESC"
            params=[before_iso]+list(team_ids)+list(team_ids)
            for r in c.execute(sql,params).fetchall():
                item=dict(r);candidates[item.get('id')]=item

        # 3) Fallback por nome, sem LIMIT antes do filtro da equipe.
        # Este é o caminho mais importante quando o provedor gravou outro ID.
        sql="SELECT * FROM matches WHERE sport='Futebol' AND start_time<? ORDER BY start_time DESC"
        for r in c.execute(sql,(before_iso,)).fetchall():
            item=dict(r)
            if not _finished_match(item):continue
            if _same(team_name,item.get('home_name')) or _same(team_name,item.get('away_name')):
                candidates[item.get('id')]=item

        # 4) Último fallback: o motor já consegue calcular médias a partir de
        # match_stats. Se os IDs da equipe estiverem divergentes, localizar os
        # jogos pelas estatísticas e depois exibir a partida correspondente.
        if len(candidates)<limit and team_ids:
            placeholders=','.join('?' for _ in team_ids)
            sql=f"""SELECT DISTINCT m.* FROM matches m
                     JOIN match_stats s ON s.match_id=m.id
                     WHERE m.sport='Futebol' AND m.status='FINISHED'
                       AND m.start_time<? AND s.team_id IN ({placeholders})
                     ORDER BY m.start_time DESC"""
            for r in c.execute(sql,[before_iso]+list(team_ids)).fetchall():
                item=dict(r);candidates[item.get('id')]=item

        return sorted(candidates.values(),key=lambda x:x.get('start_time') or '',reverse=True)[:limit]
    finally:c.close()


def player_history_for_view(team_id,team_name,before_iso,limit=20):
    result=player_history_summary(team_id,before_iso=before_iso,limit=limit) if team_id else []
    if result or not team_name:return result
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
