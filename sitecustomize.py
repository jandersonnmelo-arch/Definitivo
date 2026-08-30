"""Compatibilidade de leitura para IDs canônicos e estatísticas individuais.

A camada de leitura resolve divergências antigas de identidade sem fazer
novas chamadas de API e sem alterar os registros persistidos.
"""

import re
import unicodedata


def _norm(value):
    s = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(cr|ec|sc|se|ca|fc|cf|ac|club|football|futbol)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _same_team(a, b):
    a, b = _norm(a), _norm(b)
    return bool(a and b and (a == b or a in b or b in a))

try:
    from core import db as _db

    _original_team_history = _db.team_history
    _original_get_players = _db.get_players
    _original_player_history_summary = _db.player_history_summary

    def team_history(team_id, before_iso=None, limit=10):
        rows = _original_team_history(team_id, before_iso, limit)
        if len(rows) >= limit:
            return rows[:limit]

        connection = _db.connect()
        try:
            team = connection.execute(
                "SELECT name, normalized_name FROM teams WHERE id=?", (team_id,)
            ).fetchone()
            if not team:
                return rows

            names = {team["name"] or "", team["normalized_name"] or ""}
            existing = {r.get("id") for r in rows}
            query = "SELECT * FROM matches WHERE sport='Futebol' AND status='FINISHED'"
            params = []
            if before_iso:
                query += " AND start_time<?"
                params.append(before_iso)
            query += " ORDER BY start_time DESC"

            for raw in connection.execute(query, params).fetchall():
                item = dict(raw)
                if item.get("id") in existing:
                    continue
                if any(_same_team(name, item.get("home_name")) or _same_team(name, item.get("away_name")) for name in names if name):
                    rows.append(item)
                    existing.add(item.get("id"))
                    if len(rows) >= limit:
                        break

            rows.sort(key=lambda item: item.get("start_time") or "", reverse=True)
            return rows[:limit]
        finally:
            connection.close()

    def get_players(match_id):
        connection = _db.connect()
        try:
            match = connection.execute(
                "SELECT home_id,home_name,away_id,away_name FROM matches WHERE id=?",
                (match_id,),
            ).fetchone()
            if not match:
                return []

            rows = [dict(r) for r in connection.execute(
                """SELECT p.id,p.team_id,p.name,p.position,ps.metric,ps.value,ps.source
                   FROM players p
                   JOIN player_stats ps ON ps.player_id=p.id
                  WHERE ps.match_id=?
                  ORDER BY ps.team_id,p.name,ps.metric""",
                (match_id,),
            ).fetchall()]

            for row in rows:
                if row.get("team_id") in (match["home_id"], match["away_id"]):
                    continue
                team = connection.execute(
                    "SELECT name FROM teams WHERE id=?", (row.get("team_id"),)
                ).fetchone()
                team_name = team["name"] if team else ""
                if _same_team(team_name, match["home_name"]):
                    row["team_id"] = match["home_id"]
                elif _same_team(team_name, match["away_name"]):
                    row["team_id"] = match["away_id"]
            return rows
        finally:
            connection.close()

    def player_history_summary(team_id=None, match_id=None, before_iso=None, limit=20):
        rows = _original_player_history_summary(team_id, match_id, before_iso, limit)
        if rows or not team_id:
            return rows

        connection = _db.connect()
        try:
            team = connection.execute(
                "SELECT name,normalized_name FROM teams WHERE id=?", (team_id,)
            ).fetchone()
            if not team:
                return rows
            target_names = {team["name"] or "", team["normalized_name"] or ""}

            sql = """SELECT p.id,p.team_id,p.name,p.position,ps.match_id,ps.metric,ps.value,
                            m.start_time,m.home_name,m.away_name
                       FROM players p
                       JOIN player_stats ps ON ps.player_id=p.id
                       JOIN matches m ON m.id=ps.match_id
                      WHERE m.status='FINISHED'"""
            params = []
            if before_iso:
                sql += " AND m.start_time<?"
                params.append(before_iso)
            sql += " ORDER BY m.start_time DESC"

            grouped = {}
            for raw in connection.execute(sql, params).fetchall():
                item = dict(raw)
                if not any(_same_team(name, item.get("home_name")) or _same_team(name, item.get("away_name")) for name in target_names if name):
                    continue
                key = item["id"]
                g = grouped.setdefault(key, {
                    "team_id": team_id, "name": item["name"], "position": item.get("position"),
                    "_matches": set(), "gols": 0.0, "assistencias": 0.0, "shots": 0.0,
                    "shots_on_target": 0.0, "passes_completed": 0.0, "tackles": 0.0,
                    "fouls": 0.0, "was_fouled": 0.0, "minutes": 0.0,
                    "yellow_cards": 0.0, "red_cards": 0.0,
                })
                g["_matches"].add(item["match_id"])
                metric = item.get("metric")
                value = item.get("value")
                try: value = float(value)
                except Exception: continue
                mapping = {
                    "goals":"gols", "assists":"assistencias", "shots":"shots",
                    "shots_on_target":"shots_on_target", "passes_completed":"passes_completed",
                    "tackles":"tackles", "effectivetackles":"tackles", "fouls":"fouls",
                    "was_fouled":"was_fouled", "minutes":"minutes", "minutes_played":"minutes",
                    "yellow_cards":"yellow_cards", "red_cards":"red_cards",
                }
                if metric in mapping:
                    g[mapping[metric]] += value

            out = []
            for g in grouped.values():
                g["jogos"] = len(g.pop("_matches"))
                out.append(g)
            out.sort(key=lambda x: x.get("name") or "")
            return out[:limit]
        finally:
            connection.close()

    _db.team_history = team_history
    _db.history_coverage = lambda team_id, before_iso=None: len(team_history(team_id, before_iso, 10))
    _db.get_players = get_players
    _db.player_history_summary = player_history_summary
except Exception:
    pass

# Fallback individual para a Série B: Dados Futebol continua sendo a fonte
# primária; FotMob só entra quando não há estatísticas individuais reais.
try:
    from core import history as _history
    from providers.fotmob import FotMobProvider

    _original_enrich_details = _history._enrich_match_details

    def _enrich_with_player_fallback(match, stage='historico'):
        result = _original_enrich_details(match, stage)
        result = result if isinstance(result, dict) else {
            'success': False, 'stats': 0, 'players': [], 'player_count': 0, 'player_stats': 0
        }

        existing = []
        try:
            existing = [
                row for row in _db.get_players(match.get('id'))
                if row.get('metric') != getattr(_history, 'PRESENCE_METRIC', '__player_presence__')
                and row.get('value') is not None
            ]
        except Exception:
            pass

        if existing:
            return result

        try:
            provider = FotMobProvider()
            detail = provider.match_details(match)
            players = detail.get('players') or []
            pstats = detail.get('player_stats') or []
            stats = detail.get('stats') or []
            if players or pstats or stats:
                a, b, c, presence = _history._persist_detail(match, provider, detail)
                result['stats'] = int(result.get('stats') or 0) + a
                result['player_count'] = int(result.get('player_count') or 0) + b
                result['player_stats'] = int(result.get('player_stats') or 0) + c
                if not result.get('players'):
                    result['players'] = players
                result['success'] = bool(result.get('success') or a or b or c or presence)
                _db.add_diagnostic(
                    'diagnostico_jogadores', 'OK',
                    f'FotMob fallback: {a} estatísticas, {b} jogadores, {c} estatísticas individuais reais, {presence} presenças',
                    provider.name, match.get('id')
                )
        except Exception as exc:
            try:
                _db.add_diagnostic(
                    'diagnostico_jogadores', 'INFO',
                    f'FotMob fallback não disponível para a partida: {exc}',
                    'FotMob', match.get('id')
                )
            except Exception:
                pass

        return result

    _history._enrich_match_details = _enrich_with_player_fallback
    _history._enrich_historical_match = lambda match: _enrich_with_player_fallback(match, 'historico')
except Exception:
    pass
