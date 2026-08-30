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

            # Resolve o nome em Python para usar exatamente a mesma
            # normalização de equipes do restante do sistema.
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
        """Lê todos os jogadores persistidos da partida.

        O filtro antigo exigia que ps.team_id coincidisse literalmente com
        home_id/away_id. Isso ocultava jogadores quando uma fonte usava outro
        ID canônico para a mesma equipe. A partida já restringe o conjunto,
        então é seguro recuperar todos os player_stats daquele match e mapear
        a equipe pelo nome/identidade quando necessário.
        """
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

    _db.team_history = team_history
    _db.history_coverage = lambda team_id, before_iso=None: len(team_history(team_id, before_iso, 10))
    _db.get_players = get_players
except Exception:
    # Compatibilidade nunca deve impedir a aplicação de iniciar.
    pass
