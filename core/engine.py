from math import exp, log, lgamma

from core.db import connect
from core.normalizer import METRICS, average, source_rank


def poisson(k, lam):
    if lam is None or not isinstance(lam, (int, float)) or lam < 0 or k < 0:
        return 0.0
    if lam == 0:
        return 1.0 if k == 0 else 0.0
    try:
        log_p = -lam + k * log(lam) - lgamma(k + 1)
        if log_p < -745:
            return 0.0
        return exp(log_p)
    except (OverflowError, ValueError):
        return 0.0


def poisson_over(lam, line):
    if lam is None or line is None:
        return None
    k = int(line) + 1
    return round(max(0.0, 1 - sum(poisson(i, lam) for i in range(k))) * 100, 1)


def poisson_under(lam, line):
    if lam is None or line is None:
        return None
    k = int(line)
    return round(max(0.0, sum(poisson(i, lam) for i in range(k + 1))) * 100, 1)


def exact_total_goals(lam, max_goals=4):
    if lam is None:
        return {}
    out = {}
    for k in range(max_goals):
        out[str(k)] = round(poisson(k, lam) * 100, 1)
    out[f"{max_goals}+"] = round(
        max(0.0, 1 - sum(poisson(i, lam) for i in range(max_goals))) * 100,
        1,
    )
    return out


def outcome_probabilities(home_xg, away_xg):
    if home_xg is None or away_xg is None:
        return {"home": None, "draw": None, "away": None}

    home = draw = away = 0.0
    for x in range(12):
        for y in range(12):
            probability = poisson(x, home_xg) * poisson(y, away_xg)
            if x > y:
                home += probability
            elif x == y:
                draw += probability
            else:
                away += probability

    total = home + draw + away
    if not total:
        return {"home": None, "draw": None, "away": None}

    return {
        "home": round(home / total * 100, 1),
        "draw": round(draw / total * 100, 1),
        "away": round(away / total * 100, 1),
    }


def _team_values(team_id, metric, before, limit=10):
    metric_names = [metric]
    if metric == "effectivetackles":
        metric_names.append("tackles")

    placeholders = ",".join("?" for _ in metric_names)
    connection = connect()
    rows = connection.execute(
        f"""SELECT m.id, m.start_time, s.value, s.source, s.metric
        FROM match_stats s
        JOIN matches m ON m.id = s.match_id
        WHERE s.team_id = ?
          AND s.metric IN ({placeholders})
          AND m.status = 'FINISHED'
          AND m.start_time < ?
        ORDER BY m.start_time DESC""",
        (team_id, *metric_names, before),
    ).fetchall()
    connection.close()

    by_match = {}
    for row in rows:
        item = dict(row)
        old = by_match.get(item["id"])
        rank = (
            0 if item.get("metric") == metric else 1,
            source_rank(item.get("source")),
        )
        old_rank = (
            0 if old and old.get("metric") == metric else 1,
            source_rank(old.get("source")) if old else 99,
        )
        if old is None or rank < old_rank:
            by_match[item["id"]] = item

    selected = sorted(
        by_match.values(),
        key=lambda item: item.get("start_time") or "",
        reverse=True,
    )[:limit]
    return [item["value"] for item in selected]


def _goals(team_id, before, limit=10):
    connection = connect()
    rows = connection.execute(
        """SELECT id, home_id, away_id, home_score, away_score
        FROM matches
        WHERE sport = 'Futebol'
          AND status = 'FINISHED'
          AND start_time < ?
          AND (home_id = ? OR away_id = ?)
        ORDER BY start_time DESC
        LIMIT ?""",
        (before, team_id, team_id, limit),
    ).fetchall()
    connection.close()

    scored = []
    conceded = []
    for row in rows:
        if row["home_id"] == team_id:
            scored.append(row["home_score"])
            conceded.append(row["away_score"])
        else:
            scored.append(row["away_score"])
            conceded.append(row["home_score"])

    return average(scored), average(conceded), len(rows)


def team_profile(team_id, before, limit=10):
    scored, conceded, sample = _goals(team_id, before, limit)
    profile = {
        "sample": sample,
        "goals_for": scored,
        "goals_against": conceded,
    }

    for key in METRICS:
        if key == "goals":
            continue
        values = _team_values(team_id, key, before, limit)
        profile[key] = average(values)
        profile[f"{key}_sample"] = len(values)

    profile["xg"] = profile.get("expected_goals")
    profile["xg_sample"] = profile.get("expected_goals_sample", 0)
    return profile


def _reference_line(lam, lines):
    if lam is None or not lines:
        return None
    return min(lines, key=lambda value: abs(float(value) - lam))


def _metric_market(home, away, key, lines):
    home_value = home.get(key)
    away_value = away.get(key)
    if home_value is None and away_value is None:
        return None

    values = [
        value
        for value in (home_value, away_value)
        if isinstance(value, (int, float))
    ]
    if not values:
        return None

    total_expected = sum(values)
    line = _reference_line(total_expected, lines)
    over = poisson_over(total_expected, line)
    under = poisson_under(total_expected, line)

    return {
        "home": home_value,
        "away": away_value,
        "total_expected": round(total_expected, 2),
        "line": line,
        "over": over,
        "under": under,
        "over_probability": over,
        "under_probability": under,
        "lines": {str(line): over} if line is not None else {},
        "under_lines": {str(line): under} if line is not None else {},
    }


def _projected_value(home, away, key):
    home_value = home.get(key)
    away_value = away.get(key)
    total = None
    if isinstance(home_value, (int, float)) and isinstance(away_value, (int, float)):
        total = round(home_value + away_value, 2)

    return {
        "home": home_value,
        "away": away_value,
        "total": total,
        "sample_home": home.get(f"{key}_sample", 0),
        "sample_away": away.get(f"{key}_sample", 0),
    }


def build_pre_match_analysis(match, limit=10):
    home = (
        team_profile(match["home_id"], match.get("start_time") or "", limit)
        if match.get("home_id")
        else {"sample": 0}
    )
    away = (
        team_profile(match["away_id"], match.get("start_time") or "", limit)
        if match.get("away_id")
        else {"sample": 0}
    )

    home_attack = (
        home.get("xg")
        if home.get("xg_sample", 0) > 0
        else home.get("goals_for")
    )
    away_attack = (
        away.get("xg")
        if away.get("xg_sample", 0) > 0
        else away.get("goals_for")
    )

    home_xg = average([home_attack, away.get("goals_against")])
    away_xg = average([away_attack, home.get("goals_against")])

    xg_values = [
        value for value in (home_xg, away_xg) if isinstance(value, (int, float))
    ]
    total_xg = round(sum(xg_values), 2) if xg_values else None

    probabilities = outcome_probabilities(home_xg, away_xg)
    both_score = None
    if home_xg is not None and away_xg is not None:
        both_score = round(
            (1 - poisson(0, home_xg)) * (1 - poisson(0, away_xg)) * 100,
            1,
        )

    market_specs = {
        "finalizacoes": ("shots", (9.5, 19.5, 23.5, 27.5, 31.5)),
        "finalizacoes_no_alvo": ("shots_on_target", (5.5, 7.5, 9.5, 11.5)),
        "finalizacoes_na_trave": ("woodwork", (0.5, 1.5, 2.5)),
        "desarmes_efetivos": ("effectivetackles", (19.5, 24.5, 29.5, 34.5)),
        "escanteios": ("corners", (7.5, 8.5, 9.5, 10.5, 11.5)),
        "faltas": ("fouls", (19.5, 22.5, 25.5, 28.5)),
        "defesas": ("saves", (4.5, 6.5, 8.5, 10.5)),
        "laterais": ("player_throws", (25.5, 29.5, 33.5, 37.5)),
        "cartoes_amarelos": ("yellow_cards", (2.5, 3.5, 4.5, 5.5)),
        "cartoes_vermelhos": ("red_cards", (0.5, 1.5)),
        "impedimentos": ("offsides", (1.5, 2.5, 3.5, 4.5)),
        "tiros_de_meta": ("goal_kicks", (5.5, 7.5, 9.5, 11.5)),
        "passes_certos": ("passes_completed", (500.5, 700.5, 900.5, 1100.5)),
    }

    goal_lines = (0.5, 1.5, 2.5, 3.5)
    goal_line = _reference_line(total_xg, goal_lines)
    goal_over = poisson_over(total_xg, goal_line)
    goal_under = poisson_under(total_xg, goal_line)

    markets = {
        "gols": {
            "expected": total_xg,
            "total_expected": total_xg,
            "line": goal_line,
            "lines": {str(goal_line): goal_over} if goal_line is not None else {},
            "under_lines": {str(goal_line): goal_under} if goal_line is not None else {},
            "over": {str(goal_line): goal_over} if goal_line is not None else {},
            "under": {str(goal_line): goal_under} if goal_line is not None else {},
            "over_probability": goal_over,
            "under_probability": goal_under,
            "exact_total": exact_total_goals(total_xg, 4),
            "ambas_marcam": both_score,
        }
    }

    for name, (key, lines) in market_specs.items():
        markets[name] = _metric_market(home, away, key, lines)

    projection_keys = [
        "shots",
        "shots_on_target",
        "woodwork",
        "effectivetackles",
        "corners",
        "fouls",
        "saves",
        "player_throws",
        "yellow_cards",
        "red_cards",
        "offsides",
        "goal_kicks",
        "passes_completed",
    ]

    projections = {
        "goals": {
            "home": home_xg,
            "away": away_xg,
            "total": total_xg,
            "sample_home": home.get("sample", 0),
            "sample_away": away.get("sample", 0),
        }
    }
    for key in projection_keys:
        projections[key] = _projected_value(home, away, key)

    coverage = {
        key: {
            "home": home.get(f"{key}_sample", 0),
            "away": away.get(f"{key}_sample", 0),
        }
        for key in METRICS
    }

    return {
        "home": home,
        "away": away,
        "xg_home": home_xg,
        "xg_away": away_xg,
        "probabilities": probabilities,
        "coverage": coverage,
        "sample_home": home.get("sample", 0),
        "sample_away": away.get("sample", 0),
        "markets": markets,
        "btts": both_score,
        "projections": projections,
    }
