import json
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

from .db import connect, now_iso, record_api_usage, calls_last_minute, usage_today


# Limites da conta Dados Futebol confirmados pelo usuário.
MAX_CALLS_PER_MINUTE = 10
MAX_CALLS_PER_DAY = 100
MIN_INTERVAL_SECONDS = 6.0

_lock = threading.RLock()
_last_request_monotonic = 0.0


def _ensure_table():
    with _lock:
        c = connect()
        try:
            c.execute(
                """CREATE TABLE IF NOT EXISTS api_response_cache(
                    cache_key TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    path TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )"""
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_api_cache_provider ON api_response_cache(provider)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_api_cache_expiry ON api_response_cache(expires_at)")
            c.commit()
        finally:
            c.close()


def _key(provider, path):
    return f"{provider}|{path}"


def get_cached(provider, path, allow_stale=False):
    _ensure_table()
    c = connect()
    try:
        row = c.execute(
            "SELECT payload,expires_at FROM api_response_cache WHERE cache_key=?",
            (_key(provider, path),),
        ).fetchone()
        if not row:
            return None
        if not allow_stale and row["expires_at"] <= now_iso():
            return None
        try:
            return json.loads(row["payload"])
        except Exception:
            return None
    finally:
        c.close()


def set_cached(provider, path, payload, ttl_seconds):
    _ensure_table()
    created = datetime.now(timezone.utc)
    expires = created + timedelta(seconds=max(1, int(ttl_seconds)))
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    c = connect()
    try:
        c.execute(
            """INSERT INTO api_response_cache(cache_key,provider,path,payload,created_at,expires_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(cache_key) DO UPDATE SET
                 payload=excluded.payload,created_at=excluded.created_at,expires_at=excluded.expires_at""",
            (_key(provider, path), provider, path, serialized, created.isoformat(), expires.isoformat()),
        )
        c.commit()
    finally:
        c.close()


def _oldest_recent_call(provider):
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    c = connect()
    try:
        row = c.execute(
            "SELECT created_at FROM api_call_log WHERE provider=? AND created_at>=? ORDER BY created_at ASC LIMIT 1",
            (provider, cutoff),
        ).fetchone()
        if not row:
            return None
        try:
            return datetime.fromisoformat(row["created_at"])
        except Exception:
            return None
    finally:
        c.close()


def _last_call(provider):
    c = connect()
    try:
        row = c.execute(
            "SELECT created_at FROM api_call_log WHERE provider=? ORDER BY created_at DESC LIMIT 1",
            (provider,),
        ).fetchone()
        if not row:
            return None
        try:
            return datetime.fromisoformat(row["created_at"])
        except Exception:
            return None
    finally:
        c.close()


def wait_for_slot(provider):
    global _last_request_monotonic
    with _lock:
        while True:
            usage = usage_today(provider)
            if int(usage.get("calls", 0)) >= MAX_CALLS_PER_DAY:
                raise RuntimeError(
                    f"Limite diário interno da {provider} atingido: {MAX_CALLS_PER_DAY} chamadas."
                )

            count = calls_last_minute(provider)
            if count >= MAX_CALLS_PER_MINUTE:
                oldest = _oldest_recent_call(provider)
                if oldest:
                    wait = 60.0 - (datetime.now(timezone.utc) - oldest).total_seconds()
                    if wait > 0:
                        time.sleep(wait + 0.1)
                        continue

            elapsed_mem = time.monotonic() - _last_request_monotonic
            if _last_request_monotonic and elapsed_mem < MIN_INTERVAL_SECONDS:
                time.sleep(MIN_INTERVAL_SECONDS - elapsed_mem)
                continue

            last = _last_call(provider)
            if last:
                elapsed_db = (datetime.now(timezone.utc) - last).total_seconds()
                if elapsed_db < MIN_INTERVAL_SECONDS:
                    time.sleep(MIN_INTERVAL_SECONDS - elapsed_db)
                    continue

            _last_request_monotonic = time.monotonic()
            return


def get_json_persistent(url, path, provider, token, ttl_seconds):
    """Cache persistente + rate limit antes de qualquer chamada externa."""
    cached = get_cached(provider, path)
    if cached is not None:
        return cached

    # Se a conta já atingiu o limite, ainda podemos servir cache expirado.
    try:
        wait_for_slot(provider)
    except RuntimeError:
        stale = get_cached(provider, path, allow_stale=True)
        if stale is not None:
            return stale
        raise

    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=20,
    )
    data = response.json() if response.content else {}
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {str(data)[:300]}")

    remaining_day = None
    remaining_minute = None
    try:
        if response.headers.get("x-ratelimit-requests-remaining"):
            remaining_day = int(response.headers["x-ratelimit-requests-remaining"])
        if response.headers.get("X-RateLimit-Remaining"):
            remaining_minute = int(response.headers["X-RateLimit-Remaining"])
    except Exception:
        pass

    record_api_usage(provider, remaining_day, remaining_minute)
    set_cached(provider, path, data, ttl_seconds)
    return data
