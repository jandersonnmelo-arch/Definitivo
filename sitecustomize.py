"""Compatibilidade do histórico da interface.

O banco atual pode conter partidas históricas gravadas com o ID canônico da
fonte, enquanto algumas partidas selecionadas ainda chegam com o vínculo de
ID anterior. O motor de análise já encontra essas partidas por meio da base
persistida; esta camada garante que a visualização do histórico use a mesma
base, com fallback seguro pelo nome normalizado da equipe.

Não faz chamadas de API e não altera os dados persistidos.
"""

import re
import unicodedata


def _norm(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode().lower()
    text = re.sub(r"\b(cr|ec|sc|se|ca|fc|cf|ac)\b", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


try:
    from core import db as _db

    _original_team_history = _db.team_history

    def team_history(team_id, before_iso=None, limit=10):
        # Primeiro preserva o comportamento oficial já existente.
        rows = _original_team_history(team_id, before_iso, limit)
        if len(rows) >= limit:
            return rows[:limit]

        # Se o vínculo de ID estiver diferente, resolve a equipe pelo nome
        # canônico e procura as mesmas partidas persistidas no banco.
        connection = _db.connect()
        try:
            team = connection.execute(
                "SELECT name, normalized_name FROM teams WHERE id=?",
                (team_id,),
            ).fetchone()
            if not team:
                return rows

            normalized_name = team["normalized_name"] or _norm(team["name"])
            existing = {r.get("id") for r in rows}

            sql = """
                SELECT * FROM matches
                WHERE sport='Futebol'
                  AND status='FINISHED'
                  AND (home_id=? OR away_id=? OR
                       LOWER(REPLACE(REPLACE(home_name, '-', ' '), '.', ' '))=? OR
                       LOWER(REPLACE(REPLACE(away_name, '-', ' '), '.', ' '))=?)
            """
            params = [team_id, team_id, normalized_name, normalized_name]
            if before_iso:
                sql += " AND start_time<?"
                params.append(before_iso)
            sql += " ORDER BY start_time DESC LIMIT ?"
            params.append(limit)

            for row in connection.execute(sql, params).fetchall():
                item = dict(row)
                if item.get("id") not in existing:
                    rows.append(item)
                    existing.add(item.get("id"))
                    if len(rows) >= limit:
                        break

            rows.sort(key=lambda item: item.get("start_time") or "", reverse=True)
            return rows[:limit]
        finally:
            connection.close()

    _db.team_history = team_history
    _db.history_coverage = lambda team_id, before_iso=None: len(
        team_history(team_id, before_iso, 10)
    )
except Exception:
    # A falha aqui não impede a aplicação de iniciar; o módulo original
    # continua disponível normalmente.
    pass
