from providers.football_data import FootballDataProvider
from providers.espn import ESPNProvider
from providers.fotmob import FotMobProvider
from providers.api_football import ApiFootballProvider
from core.repository import canonical_id, upsert_match, upsert_match_stats, upsert_players, upsert_player_stats, add_diagnostic, get_provider_id
from core.competitions import competition_matches

MAX_ENRICH_BATCH = 5
PRESENCE_METRIC = '__player_presence__'


def providers():
    return [FootballDataProvider(), ESPNProvider(), FotMobProvider(), ApiFootballProvider()]


def collection_providers():
    return [FootballDataProvider(), ESPNProvider()]


def _with_player_presence(players, player_stats):
    """Garante que um jogador sem estatística individual ainda seja persistido.
    O marcador é técnico e nunca é exibido como estatística.
    """
    existing = {(str(r.get('player_id')), r.get('source')) for r in player_stats or []}
    out = list(player_stats or [])
    for p in players or []:
        pid, src = p.get('id'), p.get('source', 'unknown')
        key = (str(pid), src)
        if pid is not None and key not in existing:
            out.append({'player_id': pid, 'metric': PRESENCE_METRIC, 'value': 1.0, 'source': src})
            existing.add(key)
    return out


def collect(date_from, date_to, competitions=None, competition=None):
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
    if len(matches) > MAX_ENRICH_BATCH:
        raise ValueError('O enriquecimento é limitado a 5 partidas por operação.')
    total = 0
    for m in matches:
        for p in providers():
            if not p.available():
                continue
            try:
                if p.name == 'API-Football':
                    pid = p.resolve_match_id(m)
                elif p.name == 'FotMob':
                    pid = m
                else:
                    pid = get_provider_id(m['id'], p.name)
                if not pid:
                    continue
                d = p.match_details(pid)
                for row in d.get('stats', []):
                    row['source'] = p.name
                for row in d.get('players', []):
                    row['source'] = p.name
                    row['match_id'] = m['id']
                for row in d.get('player_stats', []):
                    row['source'] = p.name
                players = d.get('players', []) or []
                player_stats = _with_player_presence(players, d.get('player_stats', []))
                upsert_match_stats(m['id'], d.get('stats', []))
                upsert_players(players)
                upsert_player_stats(m['id'], player_stats)
                count = len(d.get('stats', [])) + len(player_stats) + len(players)
                total += count
                add_diagnostic('enriquecimento', 'OK', f'{p.name}: {count} registros processados ({len(players)} jogadores)', p.name, m['id'])
            except Exception as e:
                add_diagnostic('enriquecimento', 'ERROR', f'{p.name}: {e}', p.name, m['id'])
    return total
