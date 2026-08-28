from providers.football_data import FootballDataProvider
from providers.espn import ESPNProvider
from providers.espn_calendar import ESPNCalendarProvider
from providers.api_futebol_calendar_fixed import ApiFutebolCalendarProviderFixed
from providers.fotmob import FotMobProvider
from providers.api_football import ApiFootballProvider
from providers.dados_futebol_fixed import DadosFutebolProviderFixed
from core.repository import canonical_id, upsert_match, upsert_match_stats, upsert_players, upsert_player_stats, add_diagnostic, get_provider_id, dedupe_existing_matches
from core.db import get_stats
from core.competitions import competition_matches
from core.data_quality import reconcile_database
from core.normalizer import MATCH_DISPLAY_ORDER, canonical_match_metric
from core.espn_team_stats import fetch_team_stats

MAX_ENRICH_BATCH = 5
PRESENCE_METRIC = '__player_presence__'


def providers():
    return [DadosFutebolProviderFixed(), FootballDataProvider(), ESPNProvider(), FotMobProvider(), ApiFootballProvider()]


def collection_providers():
    return [DadosFutebolProviderFixed(), FootballDataProvider(), ApiFutebolCalendarProviderFixed(), ESPNCalendarProvider()]


def _with_player_presence(players, player_stats):
    existing = {(str(r.get('player_id')), r.get('source')) for r in player_stats or []}
    out = list(player_stats or [])
    for p in players or []:
        pid, src = p.get('id'), p.get('source', 'unknown')
        key = (str(pid), src)
        if pid is not None and key not in existing:
            out.append({'player_id': pid, 'metric': PRESENCE_METRIC, 'value': 1.0, 'source': src, 'team_id': p.get('team_id'), 'team_name': p.get('team_name')})
            existing.add(key)
    return out


def _missing_match_metrics(match):
    stats = get_stats(match['id'])
    expected = set(MATCH_DISPLAY_ORDER) - {'goals'}
    missing = {}
    for team_id in (match.get('home_id'), match.get('away_id')):
        present = {canonical_match_metric(r.get('metric')) for r in stats if r.get('team_id') == team_id and canonical_match_metric(r.get('metric'))}
        missing[team_id] = expected - present
    return missing


def _missing_metric_names(match):
    missing = _missing_match_metrics(match)
    return set().union(*(v for v in missing.values())) if missing else set()


def _fill_missing_from_espn_cdn(match, event_id):
    if not event_id:
        return 0
    try:
        missing = _missing_metric_names(match)
        if not missing:
            return 0
        rows = fetch_team_stats(event_id)
        rows = [r for r in rows if canonical_match_metric(r.get('metric')) in missing]
        if rows:
            upsert_match_stats(match['id'], rows)
        return len(rows)
    except Exception as e:
        add_diagnostic('enriquecimento_espn_cdn','WARNING',f'ESPN CDN: {e}','ESPN',match.get('id'))
        return 0


def collect(date_from, date_to, competitions=None, competition=None):
    dedupe_existing_matches()
    reconcile_database()
    selected = list(competitions or [])
    if competition and competition not in selected:
        selected.append(competition)
    result = []
    for p in collection_providers():
        try:
            rows = p.matches(date_from, date_to, None)
            if selected:
                rows = [m for m in rows if competition_matches(m.get('competition'), selected)]
            for m in rows:
                m['id'] = canonical_id(m)
                upsert_match(m)
                result.append(m)
            add_diagnostic('coleta', 'OK', f'{p.name}: {len(rows)} partidas recebidas e persistidas', p.name)
        except Exception as e:
            add_diagnostic('coleta', 'ERROR', f'{p.name}: {e}', p.name)
    return result


def enrich(matches):
    dedupe_existing_matches()
    reconcile_database()
    if len(matches) > MAX_ENRICH_BATCH:
        raise ValueError('O enriquecimento é limitado a 5 partidas por operação.')
    total = 0
    for m in matches:
        is_serie_b = 'serie b' in str(m.get('competition') or '').lower()
        ordered = [DadosFutebolProviderFixed(), FotMobProvider(), ESPNProvider()] if is_serie_b else providers()
        primary_ok = False
        for p in ordered:
            if not p.available():
                continue
            try:
                if p.name == 'Dados Futebol':
                    pid = m
                elif p.name == 'API-Football':
                    pid = p.resolve_match_id(m)
                elif p.name == 'FotMob':
                    pid = m
                else:
                    pid = get_provider_id(m['id'], p.name)
                if not pid:
                    continue
                d = p.match_details(pid)
                stats_rows = d.get('stats', []) or []
                for row in stats_rows:
                    row['source'] = p.name
                for row in d.get('players', []) or []:
                    row['source'] = p.name
                    row['match_id'] = m['id']
                for row in d.get('player_stats', []) or []:
                    row['source'] = p.name
                players = d.get('players', []) or []
                player_stats = _with_player_presence(players, d.get('player_stats', []))

                if is_serie_b and p.name != 'Dados Futebol':
                    missing_before = _missing_metric_names(m)
                    filtered_stats = [row for row in stats_rows if canonical_match_metric(row.get('metric')) in missing_before]
                    upsert_match_stats(m['id'], filtered_stats)
                    filled = len(filtered_stats)
                    total += filled
                    add_diagnostic('enriquecimento_fallback', 'OK', f'{p.name}: {filled} métricas ausentes recuperadas; restantes: {sorted(_missing_metric_names(m))}', p.name, m['id'])
                    if not _missing_metric_names(m):
                        break
                    continue

                upsert_match_stats(m['id'], stats_rows)
                upsert_players(players)
                upsert_player_stats(m['id'], player_stats)

                if p.name in ('Football-Data.org','ESPN'):
                    espn_id = pid if p.name == 'ESPN' else get_provider_id(m['id'], 'ESPN')
                    filled = _fill_missing_from_espn_cdn(m, espn_id)
                    total += filled
                    if filled:
                        add_diagnostic('enriquecimento_espn_cdn','OK',f'ESPN CDN: {filled} métricas ausentes recuperadas; restantes: {sorted(_missing_metric_names(m))}','ESPN',m['id'])

                count = len(stats_rows) + len(player_stats) + len(players)
                total += count
                primary_ok = True
                add_diagnostic('enriquecimento', 'OK', f'{p.name}: {count} registros processados ({len(players)} jogadores)', p.name, m['id'])
                if is_serie_b and not _missing_metric_names(m):
                    break
                else:
                    break
            except Exception as e:
                add_diagnostic('enriquecimento', 'ERROR', f'{p.name}: {e}', p.name, m['id'])
                if is_serie_b:
                    continue
        if is_serie_b and not primary_ok and _missing_metric_names(m):
            add_diagnostic('enriquecimento', 'WARNING', f'Série B: permanecem sem dados: {sorted(_missing_metric_names(m))}', 'Dados Futebol', m['id'])
    return total
