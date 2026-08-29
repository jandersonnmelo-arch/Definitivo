"""Persistência remota durável do banco SQLite no GitHub.

O SQLite continua sendo a base operacional. Este módulo mantém uma cópia remota
recuperável e evita que uma execução com banco parcial/antigo substitua um
snapshot remoto que contém mais dados.

Princípios:
- remoto + local são mesclados antes de cada push;
- registros existentes são identificados pela chave primária da tabela;
- em conflitos, a versão com timestamp mais recente é preferida quando existe;
- respostas 409 do GitHub são relidas e o merge é repetido;
- o restore ocorre tabela a tabela quando a tabela local está vazia;
- gravações dentro do debounce agendam um flush automático posterior;
- `force=True` permite confirmar um lote de enriquecimento imediatamente.
"""
import base64
import json
import os
import threading
import time
from datetime import datetime, timezone

import requests

REMOTE_REPO = os.getenv("DEFINITIVO_GITHUB_REPO", "jandersonnmelo-arch/Definitivo")
REMOTE_BRANCH = os.getenv("DEFINITIVO_GITHUB_BRANCH", "main")
REMOTE_PATH = os.getenv("DEFINITIVO_REMOTE_PATH", "backups/definitivo_snapshot.json")
MIN_PUSH_SECONDS = int(os.getenv("DEFINITIVO_REMOTE_PUSH_MIN_SECONDS", "20"))
MAX_PUSH_RETRIES = int(os.getenv("DEFINITIVO_REMOTE_PUSH_RETRIES", "3"))
_LAST_PUSH = 0.0
_PUSH_TIMER = None
_PUSH_TIMER_LOCK = threading.Lock()

TABLES = [
    "schema_meta", "teams", "team_sources", "matches", "match_sources",
    "match_stats", "players", "player_stats", "diagnostics", "api_usage",
    "api_call_log", "ai_match_samples", "ai_player_samples", "ai_predictions",
    "ai_model_runs", "ai_dataset_v1",
]


def _token():
    for key in ("DEFINITIVO_GITHUB_TOKEN", "GITHUB_TOKEN", "GITHUB_PAT", "GH_TOKEN"):
        if os.getenv(key):
            return os.getenv(key)
    try:
        import streamlit as st
        for key in ("DEFINITIVO_GITHUB_TOKEN", "GITHUB_TOKEN", "GITHUB_PAT", "GH_TOKEN"):
            try:
                value = st.secrets[key]
                if value:
                    return str(value)
            except Exception:
                pass
        try:
            g = st.secrets.get("github")
            if g:
                for key in ("token", "pat", "github_token"):
                    if g.get(key):
                        return str(g[key])
        except Exception:
            pass
    except Exception:
        pass
    return None


def _url():
    return f"https://api.github.com/repos/{REMOTE_REPO}/contents/{REMOTE_PATH}"


def _headers(token=None):
    token = token or _token()
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def snapshot_payload():
    from core.db import connect
    c = connect()
    try:
        existing = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        out = {
            "format": "definitivo-db-snapshot-v5",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tables": {},
        }
        for table in TABLES:
            if table in existing:
                out["tables"][table] = [dict(r) for r in c.execute(f"SELECT * FROM {table}").fetchall()]
        return out
    finally:
        c.close()


def _decode_response_payload(response):
    if response.status_code != 200:
        return None, None
    data = response.json()
    encoded = data.get("content")
    if not encoded:
        return None, data.get("sha")
    try:
        payload = json.loads(base64.b64decode(encoded.replace("\n", "")).decode("utf-8"))
        if not str(payload.get("format", "")).startswith("definitivo-db-snapshot"):
            return None, data.get("sha")
        return payload, data.get("sha")
    except Exception:
        return None, data.get("sha")


def _remote_snapshot(headers):
    try:
        r = requests.get(_url(), params={"ref": REMOTE_BRANCH}, headers=headers, timeout=20)
        if r.status_code == 404:
            return None, None, 404
        payload, sha = _decode_response_payload(r)
        if r.status_code != 200:
            return None, sha, r.status_code
        return payload, sha, 200
    except Exception as exc:
        return None, None, exc


def _primary_key_columns(table):
    from core.db import connect
    c = connect()
    try:
        rows = c.execute(f"PRAGMA table_info({table})").fetchall()
        return [r["name"] for r in sorted(rows, key=lambda x: x["pk"]) if r["pk"]]
    finally:
        c.close()


def _row_timestamp(row):
    for key in ("updated_at", "observed_at", "created_at", "last_call"):
        value = row.get(key)
        if value:
            try:
                return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
            except Exception:
                pass
    return None


def _prefer_row(local_row, remote_row):
    lt = _row_timestamp(local_row)
    rt = _row_timestamp(remote_row)
    if lt is not None and rt is not None:
        return local_row if lt >= rt else remote_row
    return local_row


def _merge_table_rows(table, local_rows, remote_rows):
    """União segura: nunca perde registros que existam somente no remoto."""
    pk = _primary_key_columns(table)
    if not pk:
        seen = set()
        out = []
        for row in list(remote_rows or []) + list(local_rows or []):
            key = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)
            if key not in seen:
                seen.add(key)
                out.append(row)
        return out

    merged = {}
    for row in remote_rows or []:
        key = tuple(row.get(k) for k in pk)
        merged[key] = dict(row)
    for row in local_rows or []:
        key = tuple(row.get(k) for k in pk)
        if key not in merged:
            merged[key] = dict(row)
        else:
            merged[key] = _prefer_row(dict(row), merged[key])
    return list(merged.values())


def _merge_snapshots(local_payload, remote_payload):
    if not remote_payload:
        return local_payload
    merged = {
        "format": "definitivo-db-snapshot-v5",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tables": {},
    }
    local_tables = local_payload.get("tables", {}) or {}
    remote_tables = remote_payload.get("tables", {}) or {}
    for table in TABLES:
        local_rows = local_tables.get(table) or []
        remote_rows = remote_tables.get(table) or []
        if local_rows or remote_rows:
            merged["tables"][table] = _merge_table_rows(table, local_rows, remote_rows)
    return merged


def _schedule_force_push(delay):
    """Agenda um único flush posterior para não perder gravações no debounce."""
    global _PUSH_TIMER
    delay = max(0.5, float(delay))
    with _PUSH_TIMER_LOCK:
        if _PUSH_TIMER is not None and _PUSH_TIMER.is_alive():
            return
        _PUSH_TIMER = threading.Timer(delay, _delayed_force_push)
        _PUSH_TIMER.daemon = True
        _PUSH_TIMER.start()


def _delayed_force_push():
    global _PUSH_TIMER
    try:
        push(force=True)
    finally:
        with _PUSH_TIMER_LOCK:
            _PUSH_TIMER = None


def push(force=False):
    """Faz push seguro do snapshot, com merge, debounce e retry em conflito."""
    global _LAST_PUSH
    token = _token()
    if not token:
        return {"pushed": False, "reason": "github_token_not_configured"}

    now = time.monotonic()
    if not force and _LAST_PUSH and now - _LAST_PUSH < MIN_PUSH_SECONDS:
        _schedule_force_push(MIN_PUSH_SECONDS - (now - _LAST_PUSH))
        return {"pushed": False, "reason": "debounced_flush_scheduled"}

    local_payload = snapshot_payload()
    headers = _headers(token)

    for attempt in range(MAX_PUSH_RETRIES):
        remote_payload, sha, status = _remote_snapshot(headers)
        if isinstance(status, Exception):
            return {"pushed": False, "reason": type(status).__name__}
        if status not in (200, 404):
            return {"pushed": False, "reason": f"github_read_{status}"}

        payload = _merge_snapshots(local_payload, remote_payload)
        content = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        body = {
            "message": "Persist database and AI snapshot",
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": REMOTE_BRANCH,
        }
        if sha:
            body["sha"] = sha

        try:
            r = requests.put(_url(), headers=headers, json=body, timeout=45)
        except Exception as exc:
            return {"pushed": False, "reason": type(exc).__name__}

        if r.status_code in (200, 201):
            _LAST_PUSH = time.monotonic()
            return {
                "pushed": True,
                "reason": "ok",
                "attempt": attempt + 1,
                "tables": len(payload.get("tables", {})),
                "bytes": len(content.encode("utf-8")),
            }

        if r.status_code == 409 and attempt + 1 < MAX_PUSH_RETRIES:
            time.sleep(0.5 * (attempt + 1))
            continue
        return {"pushed": False, "reason": f"github_write_{r.status_code}"}

    return {"pushed": False, "reason": "github_write_conflict"}


def pull():
    token = _token()
    headers = _headers(token) if token else {"Accept": "application/vnd.github+json"}
    payload, _, status = _remote_snapshot(headers)
    return payload if status == 200 else None


def restore_if_empty():
    """Restaura cada tabela vazia a partir do snapshot remoto, sem sobrescrever dados locais."""
    from core.db import connect
    payload = pull()
    if not payload:
        return {"restored": False, "reason": "no_remote_snapshot"}

    remote_tables = payload.get("tables", {}) or {}
    if not remote_tables:
        return {"restored": False, "reason": "empty_remote_snapshot"}

    c = connect()
    restored_tables = []
    restored_rows = 0
    try:
        existing = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for table in TABLES:
            rows = remote_tables.get(table) or []
            if table not in existing or not rows:
                continue
            local_count = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if local_count:
                continue
            cols = list(rows[0].keys())
            marks = ",".join("?" for _ in cols)
            names = ",".join(cols)
            inserted = 0
            for row in rows:
                c.execute(f"INSERT OR IGNORE INTO {table} ({names}) VALUES ({marks})", [row.get(k) for k in cols])
                inserted += c.rowcount if c.rowcount > 0 else 0
            if inserted:
                restored_tables.append(table)
                restored_rows += inserted
        c.commit()
        return {"restored": bool(restored_tables), "tables": restored_tables, "rows": restored_rows}
    except Exception:
        c.rollback()
        return {"restored": False, "reason": "restore_error"}
    finally:
        c.close()
