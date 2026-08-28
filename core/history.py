from datetime import datetime, timedelta, timezone
import re, unicodedata
from providers.football_data import FootballDataProvider
from providers.fotmob import FotMobProvider
from providers.espn import ESPNProvider
from core.db import get_team_provider_id, upsert_match, team_history, history_coverage, add_diagnostic, upsert_match_stats, upsert_players, upsert_player_stats, get_players, get_stats

HISTORY_MATCHES_PER_TEAM = 10
HISTORY_DAYS = 180
PRESENCE_METRIC = '__player_presence__'


def _parse_start(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except Exception:
        return None


def _norm_name(value):
    s = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'\b(fc|cf|sc|ec|ac|club|football|futbol)\b', ' ', s)
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def _same_team(a, b):
    a, b = _norm_name(a), _norm_name(b)
    return bool(a and b and (a == b or a in b or b in a))


def _history_matches_for_team(team_id, before_iso, limit=HISTORY_MATCHES_PER_TEAM):
    return team_history(team_id, before_iso, limit)


def _collect_team_history_from_football_data(team_id, before_iso, days=HISTORY_DAYS):
    provider = FootballDataProvider()
    if not provider.available():
        return []
    provider_id = get_team_provider_id(team_id, provider.name)
    if not provider_id:
        return []
    before = _parse_start(before_iso) or datetime.now(timezone.utc)
    try:
        rows = provider.team_matches(provider_id, (before - timedelta(days=days)).date().isoformat(), before.date().isoformat(), limit=100)
    except Exception as e:
        add_diagnostic('historico', 'ERROR', f'{provider.name}: {e}', provider.name)
        return []
    for m in rows:
        upsert_match(m)
    add_diagnostic('historico', 'OK', f'{provider.name}: {len(rows)} partidas históricas coletadas para a equipe', provider.name)
    return rows


def _collect_team_history_from_espn(team_name, before_iso, days=120):
    provider = ESPNProvider()
    before = _parse_start(before_iso) or datetime.now(timezone.utc)
    cur, end, rows = before.date() - timedelta(days=days), before.date(), []
    while cur <= end:
        try:
            for m in provider.matches(cur.isoformat(), cur.isoformat(), None):
                if _same_team(team_name, m.get('home_name')) or _same_team(team_name, m.get('away_name')):
                    upsert_match(m)
                    rows.append(m)
        except Exception as e:
            add_diagnostic('historico', 'ERROR', f'ESPN fixtures: {e}', provider.name)
        cur += timedelta(days=1)
    return rows


def _resolve_espn_event_id(match):
    provider = ESPNProvider()
    dt = _parse_start(match.get('start_time'))
    if not dt:
        return None
    try:
        rows = provider.matches(dt.date().isoformat(), dt.date().isoformat(), None)
        for m in rows:
            if _same_team(match.get('home_name'), m.get('home_name')) and _same_team(match.get('away_name'), m.get('away_name')):
                return m.get('provider_match_id')
        for m in rows:
            if _same_team(match.get('home_name'), m.get('away_name')) and _same_team(match.get('away_name'), m.get('home_name')):
                return m.get('provider_match_id')
    except Exception as e:
        add_diagnostic('historico', 'ERROR', f'ESPN resolver: {e}', provider.name, match.get('id'))
    return None


def _presence_rows(players, pstats):
    out = list(pstats or [])
    existing = {(str(r.get('player_id')), r.get('source')) for r in out}
    for p in players or []:
        key = (str(p.get('id')), p.get('source', 'unknown'))
        if p.get('id') is not None and key not in existing:
            out.append({'player_id': p['id'], 'metric': PRESENCE_METRIC, 'value': 1.0, 'source': p.get('source', 'unknown')})
            existing.add(key)
    return out


def _persist_detail(match, provider, d):
    stats = d.get('stats', []) or []
    players = []
    for p in d.get('players', []) or []:
        p = dict(p)
        p['source'] = provider.name
        p['match_id'] = match['id']
        players.append(p)
    pstats = []
    for row in d.get('player_stats', []) or []:
        row = dict(row)
        row['source'] = provider.name
        pstats.append(row)
    pstats = _presence_rows(players, pstats)
    if stats:
        upsert_match_stats(match['id'], stats)
    if players:
        upsert_players(players)
    if pstats:
        upsert_player_stats(match['id'], pstats)
    return len(stats), len(players), len(pstats)


def _enrich_match_details(match, stage='historico'):
    total_stats = total_players = total_pstats = 0
    success = False
    espn = ESPNProvider()
    try:
        eid = _resolve_espn_event_id(match)
        if eid:
            d = espn.match_details(eid)
            a, b, c = _persist_detail(match, espn, d)
            total_stats += a; total_players += b; total_pstats += c
            add_diagnostic(stage, 'OK', f'ESPN: {a} estatísticas, {b} jogadores, {c} individuais', espn.name, match['id'])
            success |= bool(a or b or c)
    except Exception as e:
        add_diagnostic(stage, 'ERROR', f'ESPN detalhes: {e}', espn.name, match.get('id'))
    fotmob = FotMobProvider()
    try:
        d = fotmob.match_details(match)
        a, b, c = _persist_detail(match, fotmob, d)
        total_stats += a; total_players += b; total_pstats += c
        add_diagnostic(stage, 'OK', f'FotMob: {a} estatísticas, {b} jogadores, {c} individuais', fotmob.name, match['id'])
        success |= bool(a or b or c)
    except Exception as e:
        add_diagnostic(stage, 'ERROR', f'FotMob detalhes: {e}', fotmob.name, match.get('id'))
    return {'success': success, 'stats': total_stats, 'players': total_players, 'player_stats': total_pstats}


def _enrich_historical_match(match):
    return _enrich_match_details(match, 'historico')


def build_history_for_match(match, matches_per_team=HISTORY_MATCHES_PER_TEAM, days=HISTORY_DAYS):
    before_iso = match.get('start_time') or datetime.now(timezone.utc).isoformat()
    team_ids = [x for x in (match.get('home_id'), match.get('away_id')) if x]
    all_selected = {}
    for team_id in team_ids:
        if history_coverage(team_id, before_iso) < matches_per_team:
            _collect_team_history_from_football_data(team_id, before_iso, days)
        hist = _history_matches_for_team(team_id, before_iso, matches_per_team)
        if len(hist) < matches_per_team:
            _collect_team_history_from_espn(match['home_name'] if team_id == match.get('home_id') else match['away_name'], before_iso, 120)
            hist = _history_matches_for_team(team_id, before_iso, matches_per_team)
        for h in hist:
            all_selected[h['id']] = h

    historical = sorted(all_selected.values(), key=lambda x: x.get('start_time') or '', reverse=True)[:matches_per_team * 2]
    enriched = stats_records = player_records = player_matches = 0
    for h in historical:
        if get_stats(h['id']) and get_players(h['id']):
            continue
        r = _enrich_historical_match(h)
        if r['success']:
            enriched += 1
            stats_records += r['stats']
            player_records += r['player_stats']
            if r['players'] or r['player_stats']:
                player_matches += 1

    current = _enrich_match_details(match, 'partida')
    player_records += current['player_stats']
    stats_records += current['stats']
    if current['players']:
        player_matches += 1

    home_n = len(_history_matches_for_team(team_ids[0], before_iso, matches_per_team)) if team_ids else 0
    away_n = len(_history_matches_for_team(team_ids[-1], before_iso, matches_per_team)) if team_ids else 0
    return {
        'home_matches': home_n,
        'away_matches': away_n,
        'historical_matches': len(historical),
        'player_matches_enriched': player_matches,
        'stats_records': stats_records,
        'player_records': player_records,
        'current_players': current['players'],
        'current_stats': current['stats'],
    }
