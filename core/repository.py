"""Compatibility facade for the canonical database repository.

The database-first implementation lives in core.db. This facade also
normalizes match identity and merges duplicate provider rows before writes.
"""
from datetime import datetime, timezone
import hashlib
import re
import unicodedata
from core.db import (
    canonical_player_id, canonical_team_id, connect, init_db,
    record_api_usage, usage_today, calls_last_minute,
    upsert_match as _db_upsert_match, get_provider_id,
    upsert_match_stats, upsert_players as _db_upsert_players,
    upsert_player_stats as _db_upsert_player_stats,
    add_diagnostic, get_matches, get_match, get_stats, get_players,
    get_diagnostics, team_history,
)

# Nome único de apresentação para a mesma equipe quando diferentes fontes
# usam abreviações/sufixos distintos. A identidade do jogo continua sendo
# baseada no nome normalizado + data/hora, portanto os aliases não criam
# partidas diferentes no banco.
TEAM_CANONICAL_ALIASES = {
    'flamengo': 'Flamengo',
    'cr flamengo': 'Flamengo',
    'flamengo rj': 'Flamengo',
    'corinthians': 'Corinthians',
    'sc corinthians paulista': 'Corinthians',
    'sport club corinthians paulista': 'Corinthians',
    'santos': 'Santos',
    'santos fc': 'Santos',
    'botafogo': 'Botafogo',
    'botafogo fr': 'Botafogo',
    'botafogo rj': 'Botafogo',
    'palmeiras': 'Palmeiras',
    'se palmeiras': 'Palmeiras',
    'sao paulo': 'São Paulo',
    'sao paulo fc': 'São Paulo',
    'spfc': 'São Paulo',
    'atletico mineiro': 'Atlético-MG',
    'atletico mg': 'Atlético-MG',
    'atletico mg': 'Atlético-MG',
    'atletico go': 'Atlético-GO',
    'atletico goianiense': 'Atlético-GO',
    'atletico paranaense': 'Athletico-PR',
    'athletico paranaense': 'Athletico-PR',
    'athletico pr': 'Athletico-PR',
    'cruzeiro': 'Cruzeiro',
    'cruzeiro ec': 'Cruzeiro',
    'gremio': 'Grêmio',
    'gremio fbpa': 'Grêmio',
    'internacional': 'Internacional',
    'sport club internacional': 'Internacional',
    'vasco': 'Vasco',
    'vasco da gama': 'Vasco',
    'vasco da gama saf': 'Vasco',
    'bahia': 'Bahia',
    'ec bahia': 'Bahia',
    'fortaleza': 'Fortaleza',
    'fortaleza ec': 'Fortaleza',
    'ceara': 'Ceará',
    'ceara sc': 'Ceará',
    'bragantino': 'Bragantino',
    'red bull bragantino': 'Bragantino',
    'rb bragantino': 'Bragantino',
    'juventude': 'Juventude',
    'ec juventude': 'Juventude',
    'sport': 'Sport',
    'sport recife': 'Sport',
    'avai': 'Avaí',
    'avai fc': 'Avaí',
    'atletico go': 'Atlético-GO',
    'america mineiro': 'América-MG',
    'america mg': 'América-MG',
    'goias': 'Goiás',
    'vitoria': 'Vitória',
    'coritiba': 'Coritiba',
    'chapecoense': 'Chapecoense',
}


def _norm_name(value):
    s = unicodedata.normalize('NFKD', str(value or '')).encode('ascii','ignore').decode().lower()
    s = re.sub(r'\b(cr|ec|sc|se|ca|fc|cf|ac|club|football|futbol)\b', ' ', s)
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def canonical_team_name(value):
    """Return the canonical display name for a team/provider alias."""
    raw = str(value or '').strip()
    if not raw or raw == '—':
        return raw
    key = _norm_name(raw)
    if key in TEAM_CANONICAL_ALIASES:
        return TEAM_CANONICAL_ALIASES[key]

    # Fallback seguro para nomes que diferem apenas por prefixos/sufixos
    # institucionais. Não tenta adivinhar clubes desconhecidos.
    cleaned = re.sub(r'\s+', ' ', re.sub(
        r'\b(football club|futbol club|sport club|sociedade esportiva|clube de regatas|futebol clube)\b',
        ' ', raw, flags=re.I
    )).strip(' -')
    cleaned_key = _norm_name(cleaned)
    if cleaned_key in TEAM_CANONICAL_ALIASES:
        return TEAM_CANONICAL_ALIASES[cleaned_key]
    return cleaned or raw


def _same_team_name(a, b):
    a = _norm_name(a)
    b = _norm_name(b)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    ta = set(a.split()) - {'real', 'de', 'da', 'do', 'dos', 'das'}
    tb = set(b.split()) - {'real', 'de', 'da', 'do', 'dos', 'das'}
    common = ta & tb
    return len(common) >= 2 or (len(ta) == 1 and len(tb) == 1 and common)


def _utc_minute(value):
    if not value:
        return ''
    try:
        dt = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M')
    except Exception:
        return str(value)[:16]


def canonical_id(match):
    """Stable match identity independent of provider IDs/time-zone formatting."""
    parts = [
        _norm_name(match.get('sport','Futebol')),
        _norm_name(match.get('home_name')),
        _norm_name(match.get('away_name')),
        _utc_minute(match.get('start_time')),
    ]
    return hashlib.sha1('|'.join(parts).encode()).hexdigest()[:20]


def _same_match(row, match):
    if _norm_name(row.get('sport')) != _norm_name(match.get('sport','Futebol')):
        return False
    try:
        rdt = datetime.fromisoformat(str(row.get('start_time') or '').replace('Z','+00:00'))
        mdt = datetime.fromisoformat(str(match.get('start_time') or '').replace('Z','+00:00'))
        if rdt.tzinfo is None: rdt = rdt.replace(tzinfo=timezone.utc)
        if mdt.tzinfo is None: mdt = mdt.replace(tzinfo=timezone.utc)
        if abs((rdt-mdt).total_seconds()) > 180:
            return False
    except Exception:
        if _utc_minute(row.get('start_time')) != _utc_minute(match.get('start_time')):
            return False
    rh, ra = _norm_name(row.get('home_name')), _norm_name(row.get('away_name'))
    mh, ma = _norm_name(match.get('home_name')), _norm_name(match.get('away_name'))
    return (rh == mh and ra == ma) or (rh == ma and ra == mh)


def _row_richness(c, mid):
    stats = c.execute('SELECT COUNT(*) FROM match_stats WHERE match_id=?',(mid,)).fetchone()[0]
    players = c.execute('SELECT COUNT(*) FROM player_stats WHERE match_id=?',(mid,)).fetchone()[0]
    return int(stats) + int(players)


def _merge_duplicate_matches(c, target_id, duplicate_ids):
    merged = 0
    for old_id in duplicate_ids:
        if old_id == target_id:
            continue
        c.execute('''INSERT OR IGNORE INTO match_stats(match_id,team_id,metric,value,source,observed_at)
                     SELECT ?,team_id,metric,value,source,observed_at FROM match_stats WHERE match_id=?''',(target_id,old_id))
        c.execute('''INSERT OR IGNORE INTO player_stats(match_id,player_id,team_id,metric,value,source,observed_at)
                     SELECT ?,player_id,team_id,metric,value,source,observed_at FROM player_stats WHERE match_id=?''',(target_id,old_id))
        c.execute('''INSERT OR IGNORE INTO match_sources(match_id,source,provider_match_id,updated_at)
                     SELECT ?,source,provider_match_id,updated_at FROM match_sources WHERE match_id=?''',(target_id,old_id))
        c.execute('UPDATE diagnostics SET match_id=? WHERE match_id=?',(target_id,old_id))
        c.execute('DELETE FROM match_stats WHERE match_id=?',(old_id,))
        c.execute('DELETE FROM player_stats WHERE match_id=?',(old_id,))
        c.execute('DELETE FROM match_sources WHERE match_id=?',(old_id,))
        c.execute('DELETE FROM matches WHERE id=?',(old_id,))
        merged += 1
    return merged


def upsert_match(match):
    """Write a match under one canonical ID and merge old provider duplicates."""
    m = dict(match or {})
    # Canonicaliza somente a apresentação; a identidade continua sendo
    # calculada pela forma normalizada dos nomes.
    m['home_name'] = canonical_team_name(m.get('home_name'))
    m['away_name'] = canonical_team_name(m.get('away_name'))
    mid = canonical_id(m)
    m['id'] = mid
    with connect() as c:
        rows = [dict(r) for r in c.execute(
            'SELECT * FROM matches WHERE sport=?', (m.get('sport','Futebol'),)
        ).fetchall()]
        candidates = [r for r in rows if r.get('id') != mid and _same_match(r,m)]
        if candidates:
            target_exists = c.execute('SELECT 1 FROM matches WHERE id=?',(mid,)).fetchone() is not None
            if not target_exists:
                best = max(candidates, key=lambda r: _row_richness(c,r['id']))
                old_id = best['id']
                c.execute('UPDATE matches SET id=?,home_name=?,away_name=? WHERE id=?',(mid,m['home_name'],m['away_name'],old_id))
                c.execute('UPDATE match_stats SET match_id=? WHERE match_id=?',(mid,old_id))
                c.execute('UPDATE player_stats SET match_id=? WHERE match_id=?',(mid,old_id))
                c.execute('UPDATE match_sources SET match_id=? WHERE match_id=?',(mid,old_id))
                c.execute('UPDATE diagnostics SET match_id=? WHERE match_id=?',(mid,old_id))
                candidates = [r for r in candidates if r['id'] != old_id]
            merged = _merge_duplicate_matches(c,mid,[r['id'] for r in candidates])
            if merged:
                try:
                    c.execute("INSERT INTO diagnostics(match_id,source,stage,status,message,created_at) VALUES(?,?,?,?,?,datetime('now'))",
                              (mid,'SYSTEM','qualidade_dados','OK',f'Duplicatas de partida consolidadas: {merged}'))
                except Exception:
                    pass
        c.commit()
    return _db_upsert_match(m)


def _canonical_team_for_match(c, match_id, team_name=None, raw_team_id=None):
    """Map provider team IDs back to the canonical home/away IDs of a match.

    This is important when providers use different names for the same team,
    e.g. "Racing Santander" vs "Real Racing Club de Santander". Without this
    bridge the player_stats rows are valid but get_players() filters them out
    because their team_id belongs to a second canonical team record.
    """
    if match_id:
        m = c.execute('SELECT home_id,home_name,away_id,away_name FROM matches WHERE id=?',(match_id,)).fetchone()
        if m:
            if _same_team_name(team_name, m['home_name']):
                return m['home_id']
            if _same_team_name(team_name, m['away_name']):
                return m['away_id']
    return None


def upsert_players(players):
    """Persist players while aligning provider team IDs with match teams."""
    if not players:
        return
    normalized=[]
    with connect() as c:
        for p in players:
            row=dict(p)
            row['team_name'] = canonical_team_name(row.get('team_name'))
            match_id=row.get('match_id')
            mapped=_canonical_team_for_match(c,match_id,row.get('team_name'),row.get('team_id'))
            if mapped is not None:
                row['team_id']=mapped
            normalized.append(row)
    return _db_upsert_players(normalized)


def upsert_player_stats(match_id, rows):
    """Persist individual stats using the canonical match home/away teams."""
    if not rows:
        return
    normalized=[]
    with connect() as c:
        for r in rows:
            row=dict(r)
            row['team_name'] = canonical_team_name(row.get('team_name'))
            mapped=_canonical_team_for_match(c,match_id,row.get('team_name'),row.get('team_id'))
            if mapped is not None:
                row['team_id']=mapped
            normalized.append(row)
    return _db_upsert_player_stats(match_id,normalized)


def dedupe_existing_matches():
    """One-pass repair for duplicate matches already persisted."""
    with connect() as c:
        rows = [dict(r) for r in c.execute('SELECT * FROM matches ORDER BY start_time').fetchall()]
        groups = {}
        for row in rows:
            key = canonical_id(row)
            groups.setdefault(key, []).append(row)
        total = 0
        for mid, group in groups.items():
            if len(group) < 2 and group[0]['id'] == mid:
                # Mesmo que não haja duplicata, atualiza nomes antigos para o
                # padrão canônico sem alterar o ID nem as estatísticas.
                cn_home = canonical_team_name(group[0].get('home_name'))
                cn_away = canonical_team_name(group[0].get('away_name'))
                if cn_home != group[0].get('home_name') or cn_away != group[0].get('away_name'):
                    c.execute('UPDATE matches SET home_name=?,away_name=? WHERE id=?',(cn_home,cn_away,mid))
                continue
            target = max(group, key=lambda r: _row_richness(c,r['id']))
            target_old = target['id']
            cn_home = canonical_team_name(target.get('home_name'))
            cn_away = canonical_team_name(target.get('away_name'))
            if target_old != mid:
                if c.execute('SELECT 1 FROM matches WHERE id=?',(mid,)).fetchone():
                    _merge_duplicate_matches(c,mid,[target_old])
                else:
                    c.execute('UPDATE matches SET id=?,home_name=?,away_name=? WHERE id=?',(mid,cn_home,cn_away,target_old))
                    c.execute('UPDATE match_stats SET match_id=? WHERE match_id=?',(mid,target_old))
                    c.execute('UPDATE player_stats SET match_id=? WHERE match_id=?',(mid,target_old))
                    c.execute('UPDATE match_sources SET match_id=? WHERE match_id=?',(mid,target_old))
                    c.execute('UPDATE diagnostics SET match_id=? WHERE match_id=?',(mid,target_old))
            else:
                c.execute('UPDATE matches SET home_name=?,away_name=? WHERE id=?',(cn_home,cn_away,mid))
            total += _merge_duplicate_matches(c,mid,[r['id'] for r in group if r['id'] != mid])
        c.commit()
    return total
