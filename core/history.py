from datetime import datetime,timedelta,timezone
import re,unicodedata
from providers.football_data import FootballDataProvider
from providers.fotmob import FotMobProvider
from providers.espn import ESPNProvider
from core.db import get_team_provider_id,upsert_match,team_history,history_coverage,add_diagnostic,upsert_match_stats,upsert_players,upsert_player_stats,get_players,get_stats

HISTORY_MATCHES_PER_TEAM=10
HISTORY_DAYS=180


def _parse_start(value):
    if not value:return None
    try:return datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except Exception:return None


def _norm_name(value):
    s=unicodedata.normalize('NFKD',str(value or '')).encode('ascii','ignore').decode().lower()
    s=re.sub(r'\b(fc|cf|sc|ec|ac|ca|club|football|futbol)\b',' ',s)
    return re.sub(r'[^a-z0-9]+',' ',s).strip()


def _same_team(a,b):
    a=_norm_name(a);b=_norm_name(b)
    return bool(a and b and (a==b or a in b or b in a))


def _history_matches_for_team(team_id,before_iso,limit=HISTORY_MATCHES_PER_TEAM):
    return team_history(team_id,before_iso,limit)


def _collect_team_history_from_football_data(team_id,before_iso,days=HISTORY_DAYS):
    provider=FootballDataProvider()
    if not provider.available():return []
    provider_id=get_team_provider_id(team_id,provider.name)
    if not provider_id:return []
    before=_parse_start(before_iso) or datetime.now(timezone.utc)
    date_to=before.date().isoformat();date_from=(before-timedelta(days=days)).date().isoformat()
    try:rows=provider.team_matches(provider_id,date_from,date_to,limit=100)
    except Exception as e:
        add_diagnostic('historico','ERROR',f'{provider.name}: {e}',provider.name);return []
    for m in rows:upsert_match(m)
    add_diagnostic('historico','OK',f'{provider.name}: {len(rows)} partidas históricas coletadas para a equipe',provider.name)
    return rows


def _collect_team_history_from_espn(team_name,before_iso,days=120):
    """Fallback de fixtures. Usa o scoreboard diário do ESPN e persiste o ID ESPN real."""
    provider=ESPNProvider();before=_parse_start(before_iso) or datetime.now(timezone.utc)
    date_to=before.date();date_from=(before-timedelta(days=days)).date();rows=[];cur=date_from
    while cur<=date_to:
        try:
            for m in provider.matches(cur.isoformat(),cur.isoformat(),None):
                if _same_team(team_name,m.get('home_name')) or _same_team(team_name,m.get('away_name')):
                    upsert_match(m);rows.append(m)
        except Exception as e:add_diagnostic('historico','ERROR',f'ESPN fixtures: {e}',provider.name)
        cur+=timedelta(days=1)
    return rows


def _resolve_espn_event_id(match):
    """Football-Data e ESPN têm IDs diferentes. Resolve pelo dia + equipes antes do summary."""
    provider=ESPNProvider();dt=_parse_start(match.get('start_time'))
    if not dt:return None
    try:
        rows=provider.matches(dt.date().isoformat(),dt.date().isoformat(),None)
        for m in rows:
            if _same_team(match.get('home_name'),m.get('home_name')) and _same_team(match.get('away_name'),m.get('away_name')):
                return m.get('provider_match_id')
        # Em alguns jogos a fonte inverte a ordem.
        for m in rows:
            if _same_team(match.get('home_name'),m.get('away_name')) and _same_team(match.get('away_name'),m.get('home_name')):
                return m.get('provider_match_id')
    except Exception as e:add_diagnostic('historico','ERROR',f'ESPN resolver: {e}',provider.name,match.get('id'))
    return None


def _persist_detail(match,provider,d):
    stats=d.get('stats',[]) or []
    players=[]
    for p in d.get('players',[]) or []:
        p=dict(p);p['source']=provider.name;p['match_id']=match['id'];players.append(p)
    player_stats=d.get('player_stats',[]) or []
    for row in player_stats:row['source']=provider.name
    if stats:upsert_match_stats(match['id'],stats)
    if players:upsert_players(players)
    if player_stats:upsert_player_stats(match['id'],player_stats)
    return len(stats)+len(players)+len(player_stats)


def _enrich_historical_match(match):
    # 1) ESPN primeiro: resolve o ID real da partida e traz boxscore + jogadores.
    espn=ESPNProvider()
    try:
        eid=_resolve_espn_event_id(match)
        if eid:
            d=espn.match_details(eid);count=_persist_detail(match,espn,d)
            if count:
                add_diagnostic('historico','OK',f'ESPN: {count} registros persistidos ({len(d.get("players",[]))} jogadores)',espn.name,match['id']);return True
    except Exception as e:add_diagnostic('historico','ERROR',f'ESPN detalhes: {e}',espn.name,match.get('id'))

    # 2) FotMob como segunda fonte para métricas granulares e individuais.
    fotmob=FotMobProvider()
    try:
        d=fotmob.match_details(match);count=_persist_detail(match,fotmob,d)
        if count:
            add_diagnostic('historico','OK',f'FotMob: {count} registros persistidos ({len(d.get("players",[]))} jogadores)',fotmob.name,match['id']);return True
    except Exception as e:add_diagnostic('historico','ERROR',f'FotMob detalhes: {e}',fotmob.name,match.get('id'))
    return False


def build_history_for_match(match,matches_per_team=HISTORY_MATCHES_PER_TEAM,days=HISTORY_DAYS):
    before_iso=match.get('start_time') or datetime.now(timezone.utc).isoformat();team_ids=[x for x in (match.get('home_id'),match.get('away_id')) if x];all_selected={}
    for team_id in team_ids:
        if history_coverage(team_id,before_iso)<matches_per_team:_collect_team_history_from_football_data(team_id,before_iso,days)
        hist=_history_matches_for_team(team_id,before_iso,matches_per_team)
        if len(hist)<matches_per_team:
            _collect_team_history_from_espn(match['home_name'] if team_id==match.get('home_id') else match['away_name'],before_iso,120)
            hist=_history_matches_for_team(team_id,before_iso,matches_per_team)
        for h in hist:all_selected[h['id']]=h
    historical=sorted(all_selected.values(),key=lambda x:x.get('start_time') or '',reverse=True)[:matches_per_team*2]
    enriched=0;stats_records=0;player_records=0
    for h in historical:
        # Só pula quando já existem estatísticas E jogadores; partidas com apenas um dos dois lados continuam enriquecendo.
        if get_stats(h['id']) and get_players(h['id']):continue
        if _enrich_historical_match(h):
            enriched+=1;stats_records+=len(get_stats(h['id']));player_records+=len(get_players(h['id']))
    home_n=len(_history_matches_for_team(team_ids[0],before_iso,matches_per_team)) if team_ids else 0
    away_n=len(_history_matches_for_team(team_ids[-1],before_iso,matches_per_team)) if team_ids else 0
    return {'home_matches':home_n,'away_matches':away_n,'historical_matches':len(historical),'player_matches_enriched':enriched,'stats_records':stats_records,'player_records':player_records}
