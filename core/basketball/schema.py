"""Contrato comum de dados para NBA/NBB.

A fonte pode ter métricas adicionais, mas estes campos são os que o motor
multiesporte pode consumir sem conhecer a origem.
"""

TEAM_METRICS = (
    "points_for", "points_against", "field_goals_made", "field_goals_attempted",
    "three_points_made", "three_points_attempted", "free_throws_made", "free_throws_attempted",
    "rebounds", "assists", "steals", "blocks", "turnovers",
)

PERIOD_METRICS = tuple(f"Q{q}_{suffix}" for q in range(1, 5) for suffix in ("PF", "PA", "SALDO")) + (
    "H1_PF", "H1_PA", "H1_SALDO", "H2_PF", "H2_PA", "H2_SALDO"
)

PLAYER_METRICS = (
    "minutes", "points", "two_points_made", "two_points_attempted",
    "three_points_made", "three_points_attempted", "free_throws_made", "free_throws_attempted",
    "rebounds", "assists", "steals", "blocks", "turnovers",
)


def normalize_team_row(row: dict) -> dict:
    return {
        "competition": row.get("competition"),
        "game_id": row.get("game_id"),
        "date": row.get("date"),
        "home": row.get("home"),
        "points_for": row.get("PF"),
        "points_against": row.get("PA"),
        "field_goals_made": row.get("FGM"),
        "field_goals_attempted": row.get("FGA"),
        "three_points_made": row.get("3PM"),
        "three_points_attempted": row.get("3PA"),
        "free_throws_made": row.get("FTM"),
        "free_throws_attempted": row.get("FTA"),
        "rebounds": row.get("REB"),
        "assists": row.get("AST"),
        "steals": row.get("STL"),
        "blocks": row.get("BLK"),
        "turnovers": row.get("TOV"),
        **{k: row.get(k) for k in PERIOD_METRICS},
    }


def normalize_player_row(row: dict) -> dict:
    return {
        "competition": row.get("competition"),
        "game_id": row.get("game_id"),
        "player_id": row.get("PLAYER_ID"),
        "player": row.get("Jogador"),
        "date": row.get("Data"),
        "minutes": row.get("MIN"),
        "points": row.get("PTS"),
        "two_points_made": row.get("2PM"),
        "two_points_attempted": row.get("2PA"),
        "three_points_made": row.get("3PM"),
        "three_points_attempted": row.get("3PA"),
        "free_throws_made": row.get("FTM"),
        "free_throws_attempted": row.get("FTA"),
        "rebounds": row.get("REB"),
        "assists": row.get("AST"),
        "steals": row.get("STL"),
        "blocks": row.get("BLK"),
        "turnovers": row.get("TOV"),
    }
