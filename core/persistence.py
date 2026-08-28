"""Persistência durável do banco SQLite no ambiente do Streamlit Cloud.

O banco é mantido em data/definitivo.db durante a execução e pode ser exportado
para um snapshot JSON versionável. O snapshot nunca substitui automaticamente
o banco por um banco vazio: ele serve como backup/recovery dos dados.
"""
import json
from pathlib import Path
from datetime import datetime, timezone

from core.db import connect, init_db

SNAPSHOT_PATH = Path("data/definitivo_snapshot.json")

TABLES = [
    "schema_meta", "teams", "team_sources", "matches", "match_sources",
    "match_stats", "players", "player_stats", "diagnostics", "api_usage",
    "api_call_log"
]


def export_snapshot(path=SNAPSHOT_PATH):
    """Exporta todas as tabelas do banco para um snapshot JSON seguro."""
    init_db()
    c = connect()
    try:
        payload = {
            "format": "definitivo-db-snapshot-v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tables": {},
        }
        for table in TABLES:
            rows = c.execute(f"SELECT * FROM {table}").fetchall()
            payload["tables"][table] = [dict(r) for r in rows]
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return str(target)
    finally:
        c.close()


def import_snapshot(path=SNAPSHOT_PATH):
    """Restaura um snapshot somente quando o banco atual está vazio.

    Nunca sobrescreve uma base existente. Isso evita perder o histórico por
    causa de um restart/deploy do Streamlit.
    """
    snapshot = Path(path)
    if not snapshot.exists():
        return {"restored": False, "reason": "snapshot_not_found"}
    init_db()
    c = connect()
    try:
        current = c.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        if current:
            return {"restored": False, "reason": "database_has_matches", "matches": current}
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        tables = payload.get("tables", {})
        # Inserção em ordem de dependência.
        for table in TABLES:
            rows = tables.get(table) or []
            if not rows:
                continue
            columns = list(rows[0].keys())
            marks = ",".join("?" for _ in columns)
            names = ",".join(columns)
            for row in rows:
                c.execute(f"INSERT OR IGNORE INTO {table} ({names}) VALUES ({marks})", [row.get(k) for k in columns])
        c.commit()
        return {"restored": True, "matches": c.execute("SELECT COUNT(*) FROM matches").fetchone()[0]}
    finally:
        c.close()
