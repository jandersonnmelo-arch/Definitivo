"""Snapshot remoto do banco para sobreviver a reinícios do Streamlit Cloud."""
import base64
import json
import os
import time
from datetime import datetime, timezone

import requests

REMOTE_REPO = os.getenv("DEFINITIVO_GITHUB_REPO", "jandersonnmelo-arch/Definitivo")
REMOTE_BRANCH = os.getenv("DEFINITIVO_GITHUB_BRANCH", "main")
REMOTE_PATH = os.getenv("DEFINITIVO_REMOTE_PATH", "backups/definitivo_snapshot.json")
MIN_PUSH_SECONDS = int(os.getenv("DEFINITIVO_REMOTE_PUSH_MIN_SECONDS", "20"))
_LAST_PUSH = 0.0
TABLES = ["schema_meta","teams","team_sources","matches","match_sources","match_stats","players","player_stats","diagnostics","api_usage","api_call_log","ai_match_samples"]


def _token():
    for key in ("DEFINITIVO_GITHUB_TOKEN","GITHUB_TOKEN","GITHUB_PAT","GH_TOKEN"):
        if os.getenv(key): return os.getenv(key)
    try:
        import streamlit as st
        for key in ("DEFINITIVO_GITHUB_TOKEN","GITHUB_TOKEN","GITHUB_PAT","GH_TOKEN"):
            try:
                if st.secrets[key]: return str(st.secrets[key])
            except Exception: pass
        try:
            g=st.secrets.get("github")
            if g:
                for key in ("token","pat","github_token"):
                    if g.get(key): return str(g[key])
        except Exception: pass
    except Exception: pass
    return None


def _url(): return f"https://api.github.com/repos/{REMOTE_REPO}/contents/{REMOTE_PATH}"


def snapshot_payload():
    from core.db import connect
    c=connect()
    try:
        existing={r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        out={"format":"definitivo-db-snapshot-v3","created_at":datetime.now(timezone.utc).isoformat(),"tables":{}}
        for table in TABLES:
            if table in existing:
                out["tables"][table]=[dict(r) for r in c.execute(f"SELECT * FROM {table}").fetchall()]
        return out
    finally: c.close()


def push(force=False):
    global _LAST_PUSH
    token=_token()
    if not token: return {"pushed":False,"reason":"github_token_not_configured"}
    now=time.monotonic()
    if not force and _LAST_PUSH and now-_LAST_PUSH<MIN_PUSH_SECONDS:
        return {"pushed":False,"reason":"debounced"}
    content=json.dumps(snapshot_payload(),ensure_ascii=False,indent=2,default=str)
    headers={"Authorization":f"Bearer {token}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"}
    try:
        r=requests.get(_url(),params={"ref":REMOTE_BRANCH},headers=headers,timeout=15)
        sha=r.json().get("sha") if r.status_code==200 else None
        if r.status_code not in (200,404): return {"pushed":False,"reason":f"github_read_{r.status_code}"}
        body={"message":"Persist database snapshot","content":base64.b64encode(content.encode()).decode(),"branch":REMOTE_BRANCH}
        if sha: body["sha"]=sha
        r=requests.put(_url(),headers=headers,json=body,timeout=30)
        if r.status_code in (200,201):
            _LAST_PUSH=now
            return {"pushed":True,"reason":"ok"}
        return {"pushed":False,"reason":f"github_write_{r.status_code}"}
    except Exception as exc:
        return {"pushed":False,"reason":type(exc).__name__}


def pull():
    try:
        r=requests.get(_url(),params={"ref":REMOTE_BRANCH},timeout=15)
        if r.status_code!=200: return None
        data=r.json();encoded=data.get("content")
        if not encoded:return None
        payload=json.loads(base64.b64decode(encoded.replace("\n","")).decode())
        if not payload.get("format","").startswith("definitivo-db-snapshot"):return None
        return payload
    except Exception:
        return None


def restore_if_empty():
    from core.db import connect
    c=connect()
    try:
        if c.execute("SELECT COUNT(*) FROM matches").fetchone()[0]:
            return {"restored":False,"reason":"database_has_data"}
    finally:c.close()
    payload=pull()
    if not payload or not payload.get("tables",{}).get("matches"):
        return {"restored":False,"reason":"no_remote_snapshot"}
    c=connect()
    try:
        for table in TABLES:
            rows=payload.get("tables",{}).get(table) or []
            if not rows: continue
            cols=list(rows[0].keys()); marks=",".join("?" for _ in cols); names=",".join(cols)
            for row in rows:
                c.execute(f"INSERT OR IGNORE INTO {table} ({names}) VALUES ({marks})",[row.get(k) for k in cols])
        c.commit()
        return {"restored":True,"matches":c.execute("SELECT COUNT(*) FROM matches").fetchone()[0]}
    except Exception:
        c.rollback(); return {"restored":False,"reason":"restore_error"}
    finally:c.close()
