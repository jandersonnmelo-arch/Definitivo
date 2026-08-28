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


def _norm_name(value):
    s = unicodedata.normalize('NFKD', str(value or '')).encode('ascii','ignore').decode().lower()
    s = re.sub(r'\b(cr|ec|sc|se|ca|fc|cf|ac|club|football|futbol)\b', ' ', s)
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def _same_team_name(a, b):
    a = _norm_name(a)
    b = _norm_name(b)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    # Some providers use short forms such as "Racing Santander" while the
    # canonical source stores "Real Racing Club de Santander".
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
                c.execute('UPDATE matches SET id=? WHERE id=?',(mid,old_id))
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
    """Persist players while aligning provider team IDs with match teams.

    The database layer historically accepted the provider team ID directly.
    For player enrichment that can create a second team identity when a source
    uses a different display name. Normalize that identity before the write.
    """
    if not players:
        return
    normalized=[]
    with connect() as c:
        for p in players:
            row=dict(p)
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
                continue
            target = max(group, key=lambda r: _row_richness(c,r['id']))
            target_old = target['id']
            if target_old != mid:
                if c.execute('SELECT 1 FROM matches WHERE id=?',(mid,)).fetchone():
                    _merge_duplicate_matches(c,mid,[target_old])
                else:
                    c.execute('UPDATE matches SET id=? WHERE id=?',(mid,target_old))
                    c.execute('UPDATE match_stats SET match_id=? WHERE match_id=?',(mid,target_old))
                    c.execute('UPDATE player_stats SET match_id=? WHERE match_id=?',(mid,target_old))
                    c.execute('UPDATE match_sources SET match_id=? WHERE match_id=?',(mid,target_old))
                    c.execute('UPDATE diagnostics SET match_id=? WHERE match_id=?',(mid,target_old))
            total += _merge_duplicate_matches(c,mid,[r['id'] for r in group if r['id'] != mid])
        c.commit()
    return total


__all__ = [
    'canonical_id','canonical_player_id','canonical_team_id','connect','init_db',
    'record_api_usage','usage_today','calls_last_minute','upsert_match',
    'get_provider_id','upsert_match_stats','upsert_players','upsert_player_stats',
    'add_diagnostic','get_matches','get_match','get_stats','get_players',
    'get_diagnostics','team_history','dedupe_existing_matches'
]