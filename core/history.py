from datetime import datetime,timedelta,timezone
from providers.football_data import FootballDataProvider
from providers.fotmob import FotMobProvider
from providers.espn import ESPNProvider
from core.db import get_team_provider_id,upsert_match,team_history,history_coverage,add_diagnostic,upsert_match_stats,upsert_players,upsert_player_stats

HISTORY_MATCHES_PER_TEAM=10
HISTORY_DAYS=180
HISTORY_ENRICH_MAX=20

def _parse_start(value):
    if not value:return None
    try:return datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except Exception:return None

def _history_matches_for_team(team_id,before_iso,limit=HISTORY_MATCHES_PER_TEAM):
    return team_history(team_id,before_iso,limit)

def _collect_team_history_from_football_data(team_id,before_iso,days=HISTORY_DAYS):
    provider=FootballDataProvider()
    if not provider.available():return []
    provider_id=get_team_provider_id(team_id,provider.name)
    if not provider_id:return []
    before=_parse_start(before_iso) or datetime.now(timezone.utc)
    date_to=before.date().isoformat();date_from=(before-timedelta(days=days)).date().isoformat()
    rows=provider.team_matches(provider_id,date_from,date_to,limit=100)
    for m in rows:upsert_match(m)
    add_diagnostic('historico','OK',f'{provider.name}: {len(rows)} partidas históricas coletadas para a equipe',provider.name)
    return rows

def _collect_team_history_from_espn(team_name,before_iso,days=60):
    provider=ESPNProvider()
    before=_parse_start(before_iso) or datetime.now(timezone.utc)
    date_to=before.date();date_from=(before-timedelta(days=days)).date()
    rows=[];cur=date_from
    while cur<=date_to:
        try:
            for m in provider.matches(cur.isoformat(),cur.isoformat(),None):
                names=f"{m.get('home_name','')} {m.get('away_name','')}".lower()
                if team_name.lower() in names:
                    upsert_match(m);rows.append(m)
        except Exception as e:
            add_diagnostic('historico','ERROR',f'ESPN: {e}',provider.name)
        cur+=timedelta(days=1)
    return rows

def _enrich_historical_match(match):
    # Histórico individual usa FotMob/ESPN. API-Football fica fora deste processo.
    for provider in (FotMobProvider(),ESPNProvider()):
        try:
            if not provider.available():continue
            pid=match if provider.name=='FotMob' else match.get('provider_match_id')
            if not pid:continue
            d=provider.match_details(pid)
            if d.get('stats'):upsert_match_stats(match['id'],d.get('stats',[]))
            players=[]
            for p in d.get('players',[]):
                p=dict(p);p['source']=provider.name;p['match_id']=match['id'];players.append(p)
            if players:upsert_players(players)
            if d.get('player_stats'):upsert_player_stats(match['id'],d.get('player_stats',[]))
            if d.get('players') or d.get('player_stats'):
                add_diagnostic('historico','OK',f'{provider.name}: dados individuais persistidos',provider.name,match['id'])
                return True
        except Exception as e:
            add_diagnostic('historico','ERROR',f'{provider.name}: {e}',provider.name,match['id'])
    return False

def build_history_for_match(match,matches_per_team=HISTORY_MATCHES_PER_TEAM,days=HISTORY_DAYS):
    before_iso=match.get('start_time') or datetime.now(timezone.utc).isoformat()
    team_ids=[match.get('home_id'),match.get('away_id')]
    team_ids=[x for x in team_ids if x]
    all_selected={}
    for team_id in team_ids:
        if history_coverage(team_id,before_iso)<matches_per_team:
            _collect_team_history_from_football_data(team_id,before_iso,days)
        hist=_history_matches_for_team(team_id,before_iso,matches_per_team)
        if len(hist)<matches_per_team:
            # Fallback controlado: ESPN cobre os últimos 60 dias sem tocar na API-Football.
            _collect_team_history_from_espn(match['home_name'] if team_id==match.get('home_id') else match['away_name'],before_iso,60)
            hist=_history_matches_for_team(team_id,before_iso,matches_per_team)
        for h in hist:all_selected[h['id']]=h
    historical=sorted(all_selected.values(),key=lambda x:x.get('start_time') or '',reverse=True)[:matches_per_team*2]
    enriched=0
    for h in historical:
        # Não repete chamadas se já houver jogadores persistidos para a partida.
        from core.db import get_players
        if get_players(h['id']):continue
        if _enrich_historical_match(h):enriched+=1
    return {'home_matches':len(_history_matches_for_team(team_ids[0],before_iso,matches_per_team)) if team_ids else 0,'away_matches':len(_history_matches_for_team(team_ids[-1],before_iso,matches_per_team)) if team_ids else 0,'historical_matches':len(historical),'player_matches_enriched':enriched}
