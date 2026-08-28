import re
import unicodedata
from datetime import datetime, timezone

SOURCE_PRIORITY = {'API-Futebol': 0, 'API-Football': 1, 'ESPN': 2, 'FotMob': 3, 'Football-Data.org': 4, 'LEGACY': 99}


def _norm(value):
    s = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'\b(fc|cf|sc|ec|ac|se|ca|cr|club|football|futbol|sporting|deportivo|esporte)\b', ' ', s)
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def _player_key(name, team_id):
    return (str(team_id or ''), _norm(name))


def _position_quality(position):
    return 0 if str(position or '').strip() in {'', '-', '—', 'None', 'null'} else 1


def _source_rank(source):
    return SOURCE_PRIORITY.get(str(source or ''), 50)


def reconcile_database():
    """Unifica registros históricos sem apagar os valores brutos das partidas.

    Executa uma vez por versão. Jogadores iguais de fontes diferentes passam a
    compartilhar um ID interno por equipe/nome normalizado; as linhas de
    player_stats são migradas e posições válidas são preservadas.
    """
    from core.db import connect, now_iso

    c = connect()
    marker = c.execute("SELECT value FROM schema_meta WHERE key='data_quality_v1'").fetchone()
    if marker:
        c.close()
        return {'teams_merged': 0, 'players_merged': 0, 'stats_migrated': 0}

    teams_merged = 0
    players_merged = 0
    stats_migrated = 0

    # 1) Unifica equipes que chegaram com variações de nome.
    team_rows = c.execute('SELECT id,sport,name,normalized_name FROM teams ORDER BY updated_at DESC').fetchall()
    team_groups = {}
    for r in team_rows:
        key = (str(r['sport']), _norm(r['name']))
        if not key[1]:
            continue
        team_groups.setdefault(key, []).append(dict(r))

    team_map = {}
    for _, rows in team_groups.items():
        if len(rows) < 2:
            continue
        canonical = rows[0]['id']
        for r in rows[1:]:
            old = r['id']
            if old == canonical:
                continue
            team_map[old] = canonical

    for old, new in team_map.items():
        c.execute('UPDATE matches SET home_id=? WHERE home_id=?', (new, old))
        c.execute('UPDATE matches SET away_id=? WHERE away_id=?', (new, old))
        c.execute('UPDATE match_stats SET team_id=? WHERE team_id=?', (new, old))
        c.execute('UPDATE players SET team_id=? WHERE team_id=?', (new, old))
        # team_sources tem PK (team_id,source), então migramos linha a linha.
        rows = c.execute('SELECT source,provider_team_id,updated_at FROM team_sources WHERE team_id=?', (old,)).fetchall()
        for r in rows:
            try:
                c.execute('INSERT INTO team_sources(team_id,source,provider_team_id,updated_at) VALUES(?,?,?,?)', (new, r['source'], r['provider_team_id'], r['updated_at']))
            except Exception:
                pass
        c.execute('DELETE FROM team_sources WHERE team_id=?', (old,))
        c.execute('DELETE FROM teams WHERE id=?', (old,))
        teams_merged += 1

    # 2) Unifica jogadores por equipe + nome normalizado, preservando cada fonte
    #    em player_stats e escolhendo a melhor posição disponível.
    player_rows = c.execute('SELECT id,team_id,name,position,source,provider_player_id,updated_at FROM players ORDER BY updated_at DESC').fetchall()
    groups = {}
    for r in player_rows:
        key = _player_key(r['name'], r['team_id'])
        if not key[1]:
            continue
        groups.setdefault(key, []).append(dict(r))

    for _, rows in groups.items():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda r: (_source_rank(r.get('source')), -_position_quality(r.get('position')), str(r.get('updated_at') or '')), reverse=False)
        canonical = rows[0]
        canonical_id = canonical['id']
        # Prefere uma posição não vazia; em empate, prioridade da fonte.
        position_candidates = sorted(rows, key=lambda r: (-_position_quality(r.get('position')), _source_rank(r.get('source'))))
        best_position = position_candidates[0].get('position')
        if best_position and best_position not in {'-', '—', 'None', 'null'}:
            c.execute('UPDATE players SET position=?,updated_at=? WHERE id=?', (best_position, now_iso(), canonical_id))

        for dup in rows[1:]:
            old_id = dup['id']
            stat_rows = c.execute('SELECT match_id,metric,value,source,observed_at FROM player_stats WHERE player_id=?', (old_id,)).fetchall()
            for s in stat_rows:
                try:
                    c.execute('INSERT INTO player_stats(match_id,player_id,metric,value,source,observed_at) VALUES(?,?,?,?,?,?)', (s['match_id'], canonical_id, s['metric'], s['value'], s['source'], s['observed_at']))
                    stats_migrated += 1
                except Exception:
                    # Já existe a mesma observação para o jogador canônico.
                    pass
            c.execute('DELETE FROM player_stats WHERE player_id=?', (old_id,))
            c.execute('DELETE FROM players WHERE id=?', (old_id,))
            players_merged += 1

    c.execute("INSERT INTO schema_meta(key,value) VALUES('data_quality_v1',?)", (datetime.now(timezone.utc).isoformat(),))
    c.commit()
    c.close()
    return {'teams_merged': teams_merged, 'players_merged': players_merged, 'stats_migrated': stats_migrated}
