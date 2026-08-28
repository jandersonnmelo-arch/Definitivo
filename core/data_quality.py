import re
import unicodedata
from datetime import datetime, timezone
from core.series_b_quality import reconcile_serie_b_matches

SOURCE_PRIORITY = {'ESPN': 0, 'FotMob': 1, 'API-Futebol': 2, 'API-Football': 3, 'Football-Data.org': 4, 'LEGACY': 99}

TEAM_ALIASES = {
    'bayer leverkusen': 'bayer 04 leverkusen', 'bayer 04': 'bayer 04 leverkusen', 'bayer 04 leverkusen': 'bayer 04 leverkusen',
    'bayern munich': 'bayern munchen', 'bayern munchen': 'bayern munchen', 'bayern munchen fc': 'bayern munchen', 'fc bayern munchen': 'bayern munchen',
    'atletico mineiro': 'atletico mineiro', 'atletico mg': 'atletico mineiro', 'ca mineiro': 'atletico mineiro', 'clube atletico mineiro': 'atletico mineiro', 'cam': 'atletico mineiro',
    'atletico paranaense': 'athletico paranaense', 'athletico paranaense': 'athletico paranaense', 'athletico pr': 'athletico paranaense', 'cap': 'athletico paranaense',
    'flamengo': 'flamengo', 'flamengo rj': 'flamengo', 'cr flamengo': 'flamengo', 'palmeiras': 'palmeiras', 'se palmeiras': 'palmeiras', 'sao paulo': 'sao paulo', 'sao paulo fc': 'sao paulo',
    'corinthians': 'corinthians', 'corinthians paulista': 'corinthians', 'sport corinthians paulista': 'corinthians', 'sport club corinthians paulista': 'corinthians',
    'santos': 'santos', 'santos fc': 'santos', 'gremio': 'gremio', 'gremio fbpa': 'gremio', 'internacional': 'internacional', 'sport club internacional': 'internacional',
    'cruzeiro': 'cruzeiro', 'cruzeiro esporte clube': 'cruzeiro', 'botafogo': 'botafogo', 'botafogo fr': 'botafogo', 'fluminense': 'fluminense', 'vasco da gama': 'vasco da gama', 'vasco': 'vasco da gama',
    'bahia': 'bahia', 'ec bahia': 'bahia', 'vitoria': 'vitoria', 'fortaleza': 'fortaleza', 'ceara': 'ceara', 'sport recife': 'sport recife', 'sport': 'sport recife',
    'bragantino': 'red bull bragantino', 'red bull bragantino': 'red bull bragantino', 'red bull brasil': 'red bull bragantino',
    'lille': 'lille', 'lille osc': 'lille', 'paris saint germain': 'paris saint germain', 'paris saint germain fc': 'paris saint germain', 'psg': 'paris saint germain',
    'racing santander': 'real racing club de santander', 'racing club de santander': 'real racing club de santander', 'real racing': 'real racing club de santander', 'real racing club de santander': 'real racing club de santander', 'real racing de santander': 'real racing club de santander',
    'sporting clube de portugal': 'sporting portugal', 'clube de portugal': 'sporting portugal', 'sporting portugal': 'sporting portugal', 'sporting cp': 'sporting portugal', 'sporting lisbon': 'sporting portugal',
}

def _norm(value):
    s = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().lower(); s = re.sub(r'[^a-z0-9]+', ' ', s).strip()
    if s in TEAM_ALIASES: return TEAM_ALIASES[s]
    if s in {'ca mineiro', 'atletico mg', 'clube atletico mineiro', 'atletico mineiro'}: return 'atletico mineiro'
    if s == 'cam': return 'atletico mineiro'
    s = re.sub(r'\b(fc|cf|sc|ec|ac|se|ca|cr|club|football|futbol|sporting|deportivo|esporte)\b', ' ', s); s = re.sub(r'[^a-z0-9]+', ' ', s).strip(); return TEAM_ALIASES.get(s, s)

def _team_key(value): return TEAM_ALIASES.get(_norm(value), _norm(value))
def _player_key(name, team_id): return (str(team_id or ''), _norm(name))
def _position_quality(position): return 0 if str(position or '').strip() in {'', '-', '—', 'None', 'null'} else 1
def _source_rank(source): return SOURCE_PRIORITY.get(str(source or ''), 50)
def _valid_position(position): return str(position or '').strip() not in {'', '-', '—', 'None', 'null'}

def reconcile_database(force=False):
    """Consolida identidades de equipes/jogadores e remove duplicidades de dados."""
    from core.db import connect, now_iso, init_db
    init_db(); c = connect()
    marker = c.execute("SELECT value FROM schema_meta WHERE key='data_quality_v4'").fetchone()
    if marker and not force:
        c.close(); return {'teams_merged': 0, 'players_merged': 0, 'stats_migrated': 0, 'stats_deduped': 0, 'matches_merged': 0}

    teams_merged = players_merged = stats_migrated = stats_deduped = 0
    team_rows = c.execute('SELECT id,sport,name,normalized_name,updated_at FROM teams ORDER BY updated_at DESC').fetchall(); team_groups = {}
    for r in team_rows:
        key = (str(r['sport']), _team_key(r['name']))
        if key[1]: team_groups.setdefault(key, []).append(dict(r))
    team_map = {}
    for _, rows in team_groups.items():
        if len(rows) < 2: continue
        canonical = rows[0]['id']
        for r in rows[1:]:
            if r['id'] != canonical: team_map[r['id']] = canonical
    for old, new in team_map.items():
        c.execute('UPDATE matches SET home_id=? WHERE home_id=?', (new, old)); c.execute('UPDATE matches SET away_id=? WHERE away_id=?', (new, old))
        old_stats = c.execute('SELECT match_id,metric,value,source,observed_at FROM match_stats WHERE team_id=?', (old,)).fetchall()
        for s in old_stats:
            try: c.execute('INSERT INTO match_stats(match_id,team_id,metric,value,source,observed_at) VALUES(?,?,?,?,?,?)', (s['match_id'],new,s['metric'],s['value'],s['source'],s['observed_at']))
            except Exception: pass
        c.execute('DELETE FROM match_stats WHERE team_id=?', (old,)); c.execute('UPDATE players SET team_id=? WHERE team_id=?', (new, old))
        rows = c.execute('SELECT source,provider_team_id,updated_at FROM team_sources WHERE team_id=?', (old,)).fetchall()
        for r in rows:
            try: c.execute('INSERT INTO team_sources(team_id,source,provider_team_id,updated_at) VALUES(?,?,?,?)', (new,r['source'],r['provider_team_id'],r['updated_at']))
            except Exception: pass
        c.execute('DELETE FROM team_sources WHERE team_id=?', (old,)); c.execute('DELETE FROM teams WHERE id=?', (old,)); teams_merged += 1

    player_rows = c.execute('SELECT id,team_id,name,position,source,provider_player_id,updated_at FROM players ORDER BY updated_at DESC').fetchall(); groups = {}
    for r in player_rows:
        key = _player_key(r['name'], r['team_id'])
        if key[1]: groups.setdefault(key, []).append(dict(r))
    for _, rows in groups.items():
        if len(rows) < 2: continue
        rows.sort(key=lambda r: (_source_rank(r.get('source')), -_position_quality(r.get('position')))); canonical = rows[0]; canonical_id = canonical['id']
        position_candidates = sorted(rows, key=lambda r: (-_position_quality(r.get('position')), _source_rank(r.get('source')))); best_position = position_candidates[0].get('position')
        if _valid_position(best_position): c.execute('UPDATE players SET position=?,updated_at=? WHERE id=?', (best_position,now_iso(),canonical_id))
        for dup in rows[1:]:
            old_id = dup['id']; stat_rows = c.execute('SELECT match_id,metric,value,source,observed_at FROM player_stats WHERE player_id=?', (old_id,)).fetchall()
            for s in stat_rows:
                try:
                    c.execute('INSERT INTO player_stats(match_id,player_id,metric,value,source,observed_at) VALUES(?,?,?,?,?,?)', (s['match_id'],canonical_id,s['metric'],s['value'],s['source'],s['observed_at'])); stats_migrated += 1
                except Exception: pass
            c.execute('DELETE FROM player_stats WHERE player_id=?', (old_id,)); c.execute('DELETE FROM players WHERE id=?', (old_id,)); players_merged += 1

    dup_rows = c.execute('''SELECT match_id,player_id,metric FROM player_stats WHERE metric != '__player_presence__' GROUP BY match_id,player_id,metric HAVING COUNT(*) > 1''').fetchall()
    for d in dup_rows:
        rows = c.execute('SELECT source FROM player_stats WHERE match_id=? AND player_id=? AND metric=?', (d['match_id'],d['player_id'],d['metric'])).fetchall(); ranked = sorted(rows, key=lambda r: _source_rank(r['source']))
        for r in ranked[1:]:
            c.execute('DELETE FROM player_stats WHERE match_id=? AND player_id=? AND metric=? AND source=?', (d['match_id'],d['player_id'],d['metric'],r['source'])); stats_deduped += 1

    c.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('data_quality_v4',?)", (datetime.now(timezone.utc).isoformat(),)); c.commit(); c.close()

    # Serie B uses multiple feeds with different provider IDs and small name variants.
    # Reconcile the fixture identity after teams/players have been canonicalized so
    # the duplicate rows can be merged without discarding enriched statistics.
    try:
        serie_b = reconcile_serie_b_matches()
    except Exception:
        serie_b = {'matches_merged': 0, 'sources_moved': 0, 'stats_moved': 0, 'player_stats_moved': 0}
    return {'teams_merged':teams_merged,'players_merged':players_merged,'stats_migrated':stats_migrated,'stats_deduped':stats_deduped, **serie_b}
