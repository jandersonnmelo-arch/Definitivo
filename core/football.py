from providers.football_data import FootballDataProvider
from providers.api_football import ApiFootballProvider
from core.repository import canonical_id,upsert_match,upsert_match_stats,upsert_players,upsert_player_stats,add_diagnostic

MAX_ENRICH_BATCH=5

def providers():return [FootballDataProvider(),ApiFootballProvider()]

def collect(date_from,date_to,competition=None):
    result=[]
    for p in providers():
        if not p.available():
            add_diagnostic('coleta','INFO',f'{p.name}: chave não configurada',p.name);continue
        try:
            rows=p.matches(date_from,date_to,competition)
            for m in rows:
                m['id']=canonical_id(p.name,m['provider_match_id'])
                upsert_match(m);result.append(m)
            add_diagnostic('coleta','OK',f'{p.name}: {len(rows)} partidas recebidas e persistidas',p.name)
        except Exception as e:add_diagnostic('coleta','ERROR',f'{p.name}: {e}',p.name)
    return result

def enrich(matches):
    if len(matches)>MAX_ENRICH_BATCH:raise ValueError('O enriquecimento é limitado a 5 partidas por operação.')
    by_source={}
    for m in matches:by_source.setdefault(m.get('source'),[]).append(m)
    total=0
    for p in providers():
        for m in by_source.get(p.name,[]):
            if not p.available():continue
            try:
                d=p.match_details(m['provider_match_id'])
                upsert_match_stats(m['id'],d.get('stats',[]))
                upsert_players(d.get('players',[]));upsert_player_stats(m['id'],d.get('player_stats',[]))
                total+=len(d.get('stats',[]))+len(d.get('player_stats',[]))
                add_diagnostic('enriquecimento','OK',f'{p.name}: {len(d.get("stats",[]))} estatísticas e {len(d.get("player_stats",[]))} registros de jogador',p.name,m['id'])
            except Exception as e:add_diagnostic('enriquecimento','ERROR',f'{p.name}: {e}',p.name,m['id'])
    return total
