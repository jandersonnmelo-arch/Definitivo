"""Reconciliação de partidas entre múltiplas fontes."""
import re
import unicodedata
from datetime import datetime

ALIASES = {
    "racing santander": "real racing club de santander",
    "racing club de santander": "real racing club de santander",
    "real racing": "real racing club de santander",
    "athletic": "athletic club",
    "athletic club bilbao": "athletic club",
    "sc corinthians paulista": "corinthians",
    "sport club corinthians paulista": "corinthians",
    "ca mineiro": "atletico mineiro",
    "atletico mg": "atletico mineiro",
}

def norm_team(name):
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(club|sport|soccer|fc|sc|ec|se|ca|cf|ac)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return ALIASES.get(s, s)

def _dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None

def same_match(a, b, minutes=150):
    if norm_team(a.get("home_name")) != norm_team(b.get("home_name")):
        return False
    if norm_team(a.get("away_name")) != norm_team(b.get("away_name")):
        return False
    da, db = _dt(a.get("start_time")), _dt(b.get("start_time"))
    if da and db and abs((da - db).total_seconds()) > minutes * 60:
        return False
    return True

def match_key(m):
    dt = _dt(m.get("start_time"))
    day = dt.date().isoformat() if dt else str(m.get("start_time") or "")[:10]
    return f"{norm_team(m.get('home_name'))}|{norm_team(m.get('away_name'))}|{day}"

def merge_match(base, incoming):
    out = dict(base)
    for key, value in incoming.items():
        if value not in (None, "", "unknown") and out.get(key) in (None, "", "unknown"):
            out[key] = value
    sources = {x for x in str(base.get("source", "")).split(",") if x and x != "unknown"}
    sources.update(x for x in str(incoming.get("source", "")).split(",") if x and x != "unknown")
    if sources:
        out["source"] = ",".join(sorted(sources))
    return out

def consolidate(matches):
    result = []
    for m in matches or []:
        found = next((i for i, old in enumerate(result) if same_match(old, m)), None)
        if found is None:
            result.append(dict(m))
        else:
            result[found] = merge_match(result[found], m)
    return result

def classify_match_data(match_stats_count, player_count, player_stats_count, source_count=1):
    if match_stats_count <= 0 and player_count <= 0:
        return "sem_estatisticas_e_jogadores"
    if match_stats_count <= 0:
        return "sem_estatisticas_da_partida"
    if player_count <= 0:
        return "sem_jogadores"
    if player_stats_count <= 0:
        return "sem_estatisticas_individuais"
    if source_count > 1:
        return "complementada_por_multiplas_fontes"
    return "completa"
