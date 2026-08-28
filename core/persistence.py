"""Persistência durável e backup do banco SQLite.

O SQLite continua sendo a base operacional. O snapshot é uma cópia de recuperação
que pode sobreviver a reinícios/deploys quando armazenada no diretório persistente
configurado pelo aplicativo. Nunca sobrescreve uma base que já contém dados.
"""
import json
import os
import shutil
from pathlib import Path
from datetime import datetime, timezone

from core.db import connect, init_db

BASE_DIR = Path(os.getenv("DEFINITIVO_DATA_DIR", "data"))
SNAPSHOT_PATH = BASE_DIR / "definitivo_snapshot.json"
BACKUP_DIR = BASE_DIR / "backups"

TABLES = [
    "schema_meta", "teams", "team_sources", "matches", "match_sources",
    "match_stats", "players", "player_stats", "diagnostics", "api_usage",
    "api_call_log", "ai_match_samples"
]


def _snapshot_payload():
    init_db()
    c = connect()
    try:
        payload = {
            "format": "definitivo-db-snapshot-v2",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tables": {},
        }
        existing = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for table in TABLES:
            if table not in existing:
                continue
            rows = c.execute(f"SELECT * FROM {table}").fetchall()
            payload["tables"][table] = [dict(r) for r in rows]
        return payload
    finally:
        c.close()


def export_snapshot(path=SNAPSHOT_PATH):
    """Gera snapshot atômico. Falhar o backup nunca desfaz a gravação principal."""
    payload = _snapshot_payload()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, target)
    return str(target)


def export_versioned_backup():
    """Cria uma cópia datada do snapshot para recuperação histórica."""
    target = export_snapshot()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    versioned = BACKUP_DIR / f"definitivo_{stamp}.json"
    shutil.copy2(target, versioned)
    return str(versioned)


def import_snapshot(path=SNAPSHOT_PATH):
    """Restaura somente banco vazio; jamais sobrescreve histórico existente."""
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


def ensure_persistence():
    """No boot, recupera snapshot se o banco operacional estiver vazio."""
    init_db()
    c = connect()
    try:
        count = c.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    finally:
        c.close()
    if count == 0 and SNAPSHOT_PATH.exists():
        return import_snapshot()
    return {"restored": False, "reason": "database_has_data" if count else "no_snapshot", "matches": count}
