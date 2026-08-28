import json
from datetime import datetime, timezone

from core.db import connect, get_matches
from core.engine import build_pre_match_analysis
from core.ai_db import init_ai_db, AI_SCHEMA_VERSION

DATASET_VERSION = "AI-V1"
MIN_HISTORY = 5

# Features numéricas independentes do resultado da partida.
TEAM_FEATURES = (
    "goals_for", "goals_against", "xg", "shots", "shots_on_target", "woodwork",
    "effectivetackles", "corners", "fouls", "saves", "player_throws",
    "yellow_cards", "red_cards", "offsides", "goal_kicks", "passes_completed",
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _num(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _result(home, away):
    if home is None or away is None:
        return None
    if home > away:
        return "HOME"
    if home < away:
        return "AWAY"
    return "DRAW"


def _form_points(team_id, before, limit=10):
    c = connect()
    rows = c.execute(
        """SELECT home_id, away_id, home_score, away_score
           FROM matches
           WHERE sport='Futebol' AND status='FINISHED' AND start_time < ?
             AND (home_id=? OR away_id=?)
           ORDER BY start_time DESC LIMIT ?""",
        (before, team_id, team_id, limit),
    ).fetchall()
    c.close()
    if not rows:
        return None
    points = 0
    for r in rows:
        hg, ag = _num(r['home_score']), _num(r['away_score'])
        if hg is None or ag is None:
            continue
        if hg == ag:
            points += 1
        elif (r['home_id'] == team_id and hg > ag) or (r['away_id'] == team_id and ag > hg):
            points += 3
    return round(points / len(rows), 3)


def _flat_features(analysis):
    home = analysis.get("home", {}) or {}
    away = analysis.get("away", {}) or {}
    out = {
        "sample_home": analysis.get("sample_home", 0),
        "sample_away": analysis.get("sample_away", 0),
        "xg_home": analysis.get("xg_home"),
        "xg_away": analysis.get("xg_away"),
    }
    for key in TEAM_FEATURES:
        hv, av = _num(home.get(key)), _num(away.get(key))
        out[f"home_{key}"] = hv
        out[f"away_{key}"] = av
        if hv is not None and av is not None:
            out[f"diff_{key}"] = round(hv - av, 4)
            out[f"total_{key}"] = round(hv + av, 4)
        else:
            out[f"diff_{key}"] = None
            out[f"total_{key}"] = None
    return out


def _quality(features, analysis):
    numeric = [v for k, v in features.items() if k.startswith(("home_", "away_", "xg_")) and _num(v) is not None]
    coverage = analysis.get("coverage", {}) or {}
    covered = sum(
        1 for key in TEAM_FEATURES
        if (coverage.get(key, {}) or {}).get("home", 0) >= MIN_HISTORY
        and (coverage.get(key, {}) or {}).get("away", 0) >= MIN_HISTORY
    )
    return round(min(1.0, len(numeric) / max(1, 2 * len(TEAM_FEATURES))) * 0.5 + min(1.0, covered / len(TEAM_FEATURES)) * 0.5, 3)


def init_dataset_db():
    init_ai_db()
    c = connect()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS ai_dataset_v1 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT NOT NULL UNIQUE,
            dataset_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            cutoff_time TEXT NOT NULL,
            competition TEXT,
            season TEXT,
            home_team_id TEXT,
            home_team_name TEXT NOT NULL,
            away_team_id TEXT,
            away_team_name TEXT NOT NULL,
            feature_json TEXT NOT NULL,
            feature_count INTEGER NOT NULL,
            quality_score REAL NOT NULL DEFAULT 0,
            split TEXT NOT NULL,
            training_ready INTEGER NOT NULL DEFAULT 0,
            target_home_goals REAL NOT NULL,
            target_away_goals REAL NOT NULL,
            target_result TEXT NOT NULL,
            target_over_25 INTEGER NOT NULL,
            target_btts INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ai_dataset_split ON ai_dataset_v1(split, training_ready);
        CREATE INDEX IF NOT EXISTS idx_ai_dataset_cutoff ON ai_dataset_v1(cutoff_time);
        """
    )
    c.commit()
    c.close()


def _split_for_index(index, total):
    if total <= 1:
        return "train"
    train_end = max(1, int(total * 0.70))
    valid_end = max(train_end + 1, int(total * 0.85))
    if index < train_end:
        return "train"
    if index < valid_end and total >= 3:
        return "validation"
    return "test"


def build_dataset_v1(max_matches=5000):
    """Build a chronological, leakage-safe match dataset from persisted history."""
    init_dataset_db()
    matches = [m for m in get_matches("Futebol", max_matches) if m.get("status") == "FINISHED"]
    matches.sort(key=lambda m: m.get("start_time") or "")
    total = len(matches)
    c = connect()
    built = ready = 0
    for index, match in enumerate(matches):
        before = match.get("start_time") or ""
        try:
            analysis = build_pre_match_analysis(match, limit=10)
        except Exception:
            continue
        home_goals = _num(match.get("home_score"))
        away_goals = _num(match.get("away_score"))
        if home_goals is None or away_goals is None:
            continue
        features = _flat_features(analysis)
        features["form_points_home"] = _form_points(match.get("home_id"), before)
        features["form_points_away"] = _form_points(match.get("away_id"), before)
        features["competition"] = match.get("competition")
        features["season"] = match.get("season")
        quality = _quality(features, analysis)
        split = _split_for_index(index, total)
        training_ready = int(
            split in {"train", "validation", "test"}
            and analysis.get("sample_home", 0) >= MIN_HISTORY
            and analysis.get("sample_away", 0) >= MIN_HISTORY
            and quality >= 0.50
        )
        target_result = _result(home_goals, away_goals)
        c.execute(
            """INSERT INTO ai_dataset_v1(
                match_id,dataset_version,created_at,cutoff_time,competition,season,
                home_team_id,home_team_name,away_team_id,away_team_name,feature_json,
                feature_count,quality_score,split,training_ready,target_home_goals,
                target_away_goals,target_result,target_over_25,target_btts
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(match_id) DO UPDATE SET
                dataset_version=excluded.dataset_version,created_at=excluded.created_at,
                cutoff_time=excluded.cutoff_time,competition=excluded.competition,season=excluded.season,
                home_team_id=excluded.home_team_id,home_team_name=excluded.home_team_name,
                away_team_id=excluded.away_team_id,away_team_name=excluded.away_team_name,
                feature_json=excluded.feature_json,feature_count=excluded.feature_count,
                quality_score=excluded.quality_score,split=excluded.split,
                training_ready=excluded.training_ready,target_home_goals=excluded.target_home_goals,
                target_away_goals=excluded.target_away_goals,target_result=excluded.target_result,
                target_over_25=excluded.target_over_25,target_btts=excluded.target_btts""",
            (
                match["id"], DATASET_VERSION, _now(), before, match.get("competition"), match.get("season"),
                match.get("home_id"), match.get("home_name", ""), match.get("away_id"), match.get("away_name", ""),
                json.dumps(features, ensure_ascii=False, separators=(",", ":"), default=str),
                len(features), quality, split, training_ready, home_goals, away_goals, target_result,
                int((home_goals + away_goals) > 2.5), int(home_goals > 0 and away_goals > 0),
            ),
        )
        built += 1
        ready += training_ready
    c.commit()
    c.close()
    return dataset_summary()


def dataset_summary():
    init_dataset_db()
    c = connect()
    total = c.execute("SELECT COUNT(*) FROM ai_dataset_v1").fetchone()[0]
    ready = c.execute("SELECT COUNT(*) FROM ai_dataset_v1 WHERE training_ready=1").fetchone()[0]
    train = c.execute("SELECT COUNT(*) FROM ai_dataset_v1 WHERE training_ready=1 AND split='train'").fetchone()[0]
    valid = c.execute("SELECT COUNT(*) FROM ai_dataset_v1 WHERE training_ready=1 AND split='validation'").fetchone()[0]
    test = c.execute("SELECT COUNT(*) FROM ai_dataset_v1 WHERE training_ready=1 AND split='test'").fetchone()[0]
    c.close()
    return {
        "dataset_version": DATASET_VERSION,
        "schema_version": AI_SCHEMA_VERSION,
        "total": int(total),
        "training_ready": int(ready),
        "train": int(train),
        "validation": int(valid),
        "test": int(test),
        "split_rule": "70% treino / 15% validação / 15% teste, em ordem cronológica",
        "targets": ["resultado_1X2", "over_2_5", "ambas_marcam", "gols_casa", "gols_fora"],
    }


def load_dataset(split=None, training_ready=True):
    init_dataset_db()
    c = connect()
    sql = "SELECT * FROM ai_dataset_v1 WHERE 1=1"
    params = []
    if training_ready:
        sql += " AND training_ready=1"
    if split:
        sql += " AND split=?"
        params.append(split)
    sql += " ORDER BY cutoff_time"
    rows = [dict(r) for r in c.execute(sql, params).fetchall()]
    c.close()
    for row in rows:
        row["features"] = json.loads(row.pop("feature_json"))
    return rows
