from providers.football_data import FootballDataProvider
from providers.espn import ESPNProvider
from providers.fotmob import FotMobProvider
from providers.api_football import ApiFootballProvider
from core.repository import canonical_id,upsert_match,upsert_match_stats,upsert_players,upsert_player_stats,add_diagnostic,get_provider_id
from core.competitions import competition_matches

MAX_ENRICH_BATCH=5

def providers():return [FootballDataProvider(),ESPNProvider(),FotMobProvider(),ApiFootballProvider()]
def collection_providers():return [FootballDataProvider(),ESPNProvider()]

def collect(date_from,date_to,competitions=None,competition=None):
    """Coleta somente competições selecionadas e persiste as partidas válidas."""
    selected=list(competitions or [])
    if competition and competition not in selected:selected.append(competition)
    result=[]
    for p in collection_providers():
        try:
            rows=p.matches(date_from,date_to,None)
            if selected:
                rows=[m for m in rows if competition_matches(m.get('competition'),selected)]
            for m in rows:
                m['id']=canonical_id(m);upsert_match(m);result.append(m)
            add_diagnostic('coleta','OK',f'{p.name}: {len(rows)} partidas recebidas e persistidas',p.name)
        except Exception as e:add_diagnostic('coleta','ERROR',f'{p.name}: {e}',p.name)
    return result

def enrich(matches):
    if len(matches)>MAX_ENRICH_BATCH:raise ValueError('O enriquecimento é limitado a 5 partidas por operação.')
    total=0
    for m in matches:
        for p in providers():
            if not p.available():continue
            try:
                if p.name=='API-Football':pid=p.resolve_match_id(m)
                elif p.name=='FotMob':pid=m
                else:pid=get_provider_id(m['id'],p.name)
                if not pid:continue
                d=p.match_details(pid)
                for row in d.get('stats',[]):row['source']=p.name
                for row in d.get('players',[]):row['source']=p.name;row['match_id']=m['id']
                for row in d.get('player_stats',[]):row['source']=p.name
                upsert_match_stats(m['id'],d.get('stats',[]));upsert_players(d.get('players',[]));upsert_player_stats(m['id'],d.get('player_stats',[]))
                count=len(d.get('stats',[]))+len(d.get('player_stats',[]));total+=count
                add_diagnostic('enriquecimento','OK',f'{p.name}: {count} registros processados',p.name,m['id'])
            except Exception as e:add_diagnostic('enriquecimento','ERROR',f'{p.name}: {e}',p.name,m['id'])
    return total
