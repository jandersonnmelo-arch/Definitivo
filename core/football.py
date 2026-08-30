from providers.football_data import FootballDataProvider
from providers.espn import ESPNProvider
from providers.espn_calendar import ESPNCalendarProvider
from providers.fotmob import FotMobProvider
from providers.tribuna import TribunaProvider
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
TARGET_PLAYER_METRICS = {'passes_completed', 'tackles', 'tackles_won'}


def providers():
    return [DadosFutebolProviderFixed(), FootballDataProvider(), ESPNProvider(), FotMobProvider(), ApiFootballProvider()]


def collection_providers():
    # CALENDÁRIO: somente as fontes gerais do aplicativo.
    # A API Dados Futebol e a API-Futebol NÃO participam da coleta/calendário.
    # Dados Futebol é reservada exclusivamente ao enriquecimento da Série B.
    return [FootballDataProvider(), ESPNCalendarProvider()]


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


def _attach_player_teams(players, player_stats):
    by_player = {}
    for p in players or []:
        by_player[(str(p.get('id')), p.get('source'))] = p
        by_player.setdefault(str(p.get('id')), p)
    out = []
    for r in player_stats or []:
        p = by_player.get((str(r.get('player_id')), r.get('source'))) or by_player.get(str(r.get('player_id')))
        row = dict(r)
        if p:
            if row.get('team_id') is None: row['team_id'] = p.get('team_id')
            if row.get('team_name') is None: row['team_name'] = p.get('team_name')
        out.append(row)
    return out


def _merge_players(existing, incoming):
    out = list(existing or [])
    index = {(str(p.get('id')), str(p.get('team_id'))): i for i, p in enumerate(out)}
    for p in incoming or []:
        key = (str(p.get('id')), str(p.get('team_id')))
        if key not in index:
            index[key] = len(out); out.append(dict(p)); continue
        cur = out[index[key]]
        for field in ('name', 'position', 'team_name', 'team_id'):
            if cur.get(field) in (None, '', '—') and p.get(field) not in (None, '', '—'): cur[field] = p.get(field)
    return out


def canonical_player_metric_safe(metric):
    try:
        from core.normalizer import canonical_player_metric
        return canonical_player_metric(metric) or str(metric or '')
    except Exception:
        return str(metric or '')


def _stat_key(row):
    return (str(row.get('player_id')), canonical_player_metric_safe(row.get('metric')), row.get('value'), str(row.get('source') or ''))


def _merge_player_stats(existing, incoming):
    out = list(existing or [])
    seen = {_stat_key(r) for r in out}
    for r in incoming or []:
        row = dict(r); key = _stat_key(row)
        if key in seen: continue
        out.append(row); seen.add(key)
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


def _missing_player_metrics(player_stats):
    present = {canonical_player_metric_safe(r.get('metric')) for r in player_stats or [] if r.get('value') is not None}
    return TARGET_PLAYER_METRICS - present


def _fill_missing_from_espn_cdn(match, event_id):
    if not event_id: return 0
    try:
        missing = _missing_metric_names(match)
        if not missing: return 0
        rows = [r for r in fetch_team_stats(event_id) if canonical_match_metric(r.get('metric')) in missing]
        if rows: upsert_match_stats(match['id'], rows)
        return len(rows)
    except Exception as e:
        add_diagnostic('enriquecimento_espn_cdn','WARNING',f'ESPN CDN: {e}','ESPN',match.get('id')); return 0


def _fill_missing_from_tribuna(match):
    try:
        wanted = {'player_throws', 'goal_kicks'} & _missing_metric_names(match)
        if not wanted: return 0
        provider = TribunaProvider()
        if not provider.available(): return 0
        d = provider.match_details(match)
        rows = [dict(r) for r in (d.get('stats') or []) if canonical_match_metric(r.get('metric')) in wanted and r.get('value') is not None]
        if rows: upsert_match_stats(match['id'], rows)
        return len(rows)
    except Exception as e:
        add_diagnostic('enriquecimento_tribuna','WARNING',f'Tribuna: {e}','Tribuna',match.get('id')); return 0


def collect(date_from, date_to, competitions=None, competition=None):
    dedupe_existing_matches(); reconcile_database()
    selected = list(competitions or [])
    if competition and competition not in selected: selected.append(competition)
    result = []
    for p in collection_providers():
        try:
            rows = p.matches(date_from, date_to, None)
            if selected: rows = [m for m in rows if competition_matches(m.get('competition'), selected)]
            for m in rows:
                m['id'] = canonical_id(m); upsert_match(m); result.append(m)
            add_diagnostic('coleta','OK',f'{p.name}: {len(rows)} partidas recebidas e persistidas',p.name)
        except Exception as e: add_diagnostic('coleta','ERROR',f'{p.name}: {e}',p.name)
    return result


def enrich(matches):
    dedupe_existing_matches(); reconcile_database()
    if len(matches) > MAX_ENRICH_BATCH: raise ValueError('O enriquecimento é limitado a 5 partidas por operação.')
    total = 0
    for m in matches:
        is_serie_b = 'serie b' in str(m.get('competition') or '').lower()
        # REGRA DA SÉRIE B: somente Dados Futebol pode enriquecer.
        # Não existe fallback para ESPN/FotMob/API-Football neste caso.
        ordered = [DadosFutebolProviderFixed()] if is_serie_b else providers()
        primary_ok = False; accumulated_players = []; accumulated_player_stats = []; any_player_data = False
        for p in ordered:
            if not p.available(): continue
            try:
                if p.name == 'Dados Futebol': pid = m
                elif p.name == 'API-Football': pid = p.resolve_match_id(m)
                elif p.name == 'FotMob': pid = m
                else: pid = get_provider_id(m['id'], p.name)
                if not pid: continue
                d = p.match_details(pid)
                stats_rows = d.get('stats', []) or []; players = d.get('players', []) or []; player_stats = d.get('player_stats', []) or []
                for row in stats_rows: row['source'] = p.name
                for row in players: row['source'] = p.name; row['match_id'] = m['id']
                for row in player_stats: row['source'] = p.name
                player_stats = _attach_player_teams(players, player_stats)
                player_stats = _with_player_presence(players, player_stats)

                if is_serie_b:
                    missing_before = _missing_metric_names(m)
                    filtered_stats = [row for row in stats_rows if canonical_match_metric(row.get('metric')) in missing_before]
                    if filtered_stats: upsert_match_stats(m['id'], filtered_stats)
                    total += len(filtered_stats)
                    if players:
                        accumulated_players = _merge_players(accumulated_players, players)
                        accumulated_player_stats = _merge_player_stats(accumulated_player_stats, player_stats)
                        any_player_data = True
                    if not _missing_metric_names(m) and accumulated_players:
                        upsert_players(accumulated_players); upsert_player_stats(m['id'], accumulated_player_stats); primary_ok = True; break
                    continue

                if stats_rows: upsert_match_stats(m['id'], stats_rows)
                if players:
                    accumulated_players = _merge_players(accumulated_players, players)
                    accumulated_player_stats = _merge_player_stats(accumulated_player_stats, player_stats)
                    any_player_data = True
                    upsert_players(accumulated_players); upsert_player_stats(m['id'], accumulated_player_stats)

                if p.name in ('Football-Data.org','ESPN'):
                    espn_id = pid if p.name == 'ESPN' else get_provider_id(m['id'], 'ESPN')
                    filled = _fill_missing_from_espn_cdn(m, espn_id); total += filled
                    if filled: add_diagnostic('enriquecimento_espn_cdn','OK',f'ESPN CDN: {filled} métricas ausentes recuperadas; restantes: {sorted(_missing_metric_names(m))}','ESPN',m['id'])

                count = len(stats_rows) + len(player_stats) + len(players); total += count
                missing_team_stats = bool(_missing_metric_names(m)); primary_ok = True
                missing_player = _missing_player_metrics(accumulated_player_stats)
                add_diagnostic('enriquecimento','OK',f'{p.name}: {count} registros; {len(players)} jogadores; stats individuais: {len(player_stats)}; faltam métricas individuais: {sorted(missing_player)}',p.name,m['id'])
                if any_player_data and not missing_team_stats and not missing_player: break
            except Exception as e:
                add_diagnostic('enriquecimento','ERROR',f'{p.name}: {e}',p.name,m['id'])
                if is_serie_b: continue
        if accumulated_players:
            upsert_players(accumulated_players); upsert_player_stats(m['id'], accumulated_player_stats)
        if not primary_ok: add_diagnostic('enriquecimento','WARNING','Nenhum provider conseguiu concluir o enriquecimento direto.',None,m['id'])
        if not is_serie_b:
            total += _fill_missing_from_tribuna(m)
    return total
