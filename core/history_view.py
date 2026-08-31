import re
import unicodedata
from datetime import datetime, timezone
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


def _parse_dt(value):
    if not value:
        return None
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _finished_match(item):
    status=str(item.get('status') or '').strip().upper()
    if status in {'FINISHED','FT','FINAL','FINALIZADO','AET','PEN','POSTGAME','STATUS_FINAL'}:
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
    de nomes/IDs diferentes. A visualização resolve isso por ID, por todas as
    identidades equivalentes e, como garantia final, pelo nome gravado na própria
    partida. A comparação de datas é feita como datetime, evitando problemas de
    comparação textual entre formatos/offsets diferentes.
    """
    if not team_id and not team_name:
        return []

    c=connect()
    try:
        candidates={}

        # 1) Mantém o caminho oficial já usado pelo banco.
        if team_id:
            try:
                for row in team_history(team_id,before_iso,limit):
                    candidates[row.get('id')]=row
            except Exception:
                pass

        # 2) Resolve todas as identidades equivalentes da tabela teams.
        team_ids={team_id} if team_id else set()
        team_ids.update(_name_team_ids(c,team_name))
        if team_ids:
            placeholders=','.join('?' for _ in team_ids)
            sql=f"SELECT * FROM matches WHERE sport='Futebol' AND (home_id IN ({placeholders}) OR away_id IN ({placeholders}))"
            params=list(team_ids)+list(team_ids)
            for r in c.execute(sql,params).fetchall():
                item=dict(r)
                if not _finished_match(item):
                    continue
                dt=_parse_dt(item.get('start_time'))
                before=_parse_dt(before_iso)
                if before and dt and dt>=before:
                    continue
                if before and not dt:
                    continue
                candidates[item.get('id')]=item

        # 3) Garantia por nome da partida. Não há LIMIT antes de identificar
        # a equipe; isso cobre partidas persistidas com IDs canônicos antigos,
        # nomes de provedor ou equipes como Rayo/Barcelona/Corinthians/Santos.
        before=_parse_dt(before_iso)
        rows=c.execute("SELECT * FROM matches WHERE sport='Futebol'").fetchall()
        for r in rows:
            item=dict(r)
            if not _finished_match(item):
                continue
            dt=_parse_dt(item.get('start_time'))
            if before and dt and dt>=before:
                continue
            if before and not dt:
                continue
            if _same(team_name,item.get('home_name')) or _same(team_name,item.get('away_name')):
                candidates[item.get('id')]=item

        def sort_key(item):
            dt=_parse_dt(item.get('start_time'))
            return dt or datetime.min.replace(tzinfo=timezone.utc)

        return sorted(candidates.values(),key=sort_key,reverse=True)[:limit]
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
