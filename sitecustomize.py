"""Compatibilidade do histórico da interface.

O banco atual pode conter partidas históricas gravadas com o ID canônico da
fonte, enquanto algumas partidas selecionadas ainda chegam com o vínculo de
ID anterior. O motor de análise já encontra essas partidas por meio da base
persistida; esta camada garante que a visualização do histórico use a mesma
base, com fallback seguro pelo nome da equipe.

Não faz chamadas de API e não altera os dados persistidos.
"""

try:
    from core import db as _db

    _original_team_history = _db.team_history

    def team_history(team_id, before_iso=None, limit=10):
        rows = _original_team_history(team_id, before_iso, limit)
        if len(rows) >= limit:
            return rows[:limit]

        connection = _db.connect()
        try:
            team = connection.execute(
                "SELECT name, normalized_name FROM teams WHERE id=?",
                (team_id,),
            ).fetchone()
            if not team:
                return rows

            team_name = team["name"] or ""
            normalized_name = team["normalized_name"] or ""
            existing = {r.get("id") for r in rows}

            # Fallback por nome é usado somente quando o vínculo de ID não
            # trouxe os 10 jogos. Assim, partidas persistidas continuam sendo
            # a única fonte e não há qualquer nova chamada externa.
            sql = """
                SELECT * FROM matches
                WHERE sport='Futebol'
                  AND status='FINISHED'
                  AND (
                      home_id=? OR away_id=? OR
                      LOWER(home_name)=LOWER(?) OR
                      LOWER(away_name)=LOWER(?) OR
                      LOWER(home_name)=LOWER(?) OR
                      LOWER(away_name)=LOWER(?)
                  )
            """
            params = [
                team_id,
                team_id,
                team_name,
                team_name,
                normalized_name,
                normalized_name,
            ]
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
    # Nunca impedir a inicialização da aplicação por causa desta
    # compatibilidade. O módulo original continua disponível.
    pass
