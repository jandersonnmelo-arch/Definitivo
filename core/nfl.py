from __future__ import annotations

from datetime import date, timedelta
import os
import time
from zoneinfo import ZoneInfo

import requests
import pandas as pd

from core.db import record_api_usage, usage_today, calls_last_minute

BASE = 'https://v1.american-football.api-sports.io'
LEAGUE_NFL = 1
SEASON = 2026
MANAUS = ZoneInfo('America/Manaus')
PROVIDER = 'API-NFL/API-Sports'
DAILY_SOFT_LIMIT = 90
MINUTE_SOFT_LIMIT = 8
S = requests.Session()

NFL_TEAMS = {
    'Atlanta Falcons':'ATL','Arizona Cardinals':'ARI','Baltimore Ravens':'BAL','Buffalo Bills':'BUF','Carolina Panthers':'CAR','Chicago Bears':'CHI','Cincinnati Bengals':'CIN','Cleveland Browns':'CLE','Dallas Cowboys':'DAL','Denver Broncos':'DEN','Detroit Lions':'DET','Green Bay Packers':'GB','Houston Texans':'HOU','Indianapolis Colts':'IND','Jacksonville Jaguars':'JAX','Kansas City Chiefs':'KC','Las Vegas Raiders':'LV','Los Angeles Chargers':'LAC','Los Angeles Rams':'LAR','Miami Dolphins':'MIA','Minnesota Vikings':'MIN','New England Patriots':'NE','New Orleans Saints':'NO','New York Giants':'NYG','New York Jets':'NYJ','Philadelphia Eagles':'PHI','Pittsburgh Steelers':'PIT','San Francisco 49ers':'SF','Seattle Seahawks':'SEA','Tampa Bay Buccaneers':'TB','Tennessee Titans':'TEN','Washington Commanders':'WSH'
}


def _secret():
    names = ('API_SPORTS_KEY','API_NFL_KEY','API_FOOTBALL_KEY','APISPORTS_KEY')
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    try:
        import streamlit as st
        for n in names:
            try:
                v = st.secrets.get(n)
            except Exception:
                v = None
            if v:
                return v
        try:
            block = st.secrets.get('api_futebol')
            if block:
                for k in ('token','key','api_key'):
                    try: v = block.get(k)
                    except Exception: v = None
                    if v: return v
        except Exception:
            pass
    except Exception:
        pass
    return None


def _guard():
    key = _secret()
    if not key:
        raise RuntimeError('chave API-Sports não configurada. Use API_SPORTS_KEY nos Secrets.')
    u = usage_today(PROVIDER)
    if int(u.get('calls', 0)) >= DAILY_SOFT_LIMIT:
        raise RuntimeError(f'proteção diária ativa ({u.get("calls",0)} chamadas registradas hoje)')
    if calls_last_minute(PROVIDER) >= MINUTE_SOFT_LIMIT:
        raise RuntimeError('proteção por minuto ativa; aguarde antes de novas chamadas')
    return key


def api_get(path='', params=None):
    key = _guard()
    url = f'{BASE}/{path.lstrip("/")}'
    last = None
    for attempt in range(3):
        try:
            r = S.get(url, params=params or {}, headers={'x-apisports-key': key}, timeout=(10, 30))
            record_api_usage(PROVIDER, r.headers.get('x-ratelimit-requests-remaining'), r.headers.get('x-ratelimit-requests-minute-remaining'))
            r.raise_for_status()
            data = r.json()
            errors = data.get('errors')
            if errors and errors != [] and errors != {}:
                raise RuntimeError(f'API-NFL retornou erro: {errors}')
            return data
        except (requests.RequestException, ValueError, RuntimeError) as e:
            last = e
            if attempt < 2:
                time.sleep(attempt + 1)
    raise RuntimeError(f'Falha na fonte NFL/API-Sports: {last}')


def _manaus(dt_value):
    dt = pd.to_datetime(dt_value, utc=True, errors='coerce')
    if pd.isna(dt):
        return None
    return dt.tz_convert(MANAUS)


def _game_datetime(game):
    d = ((game.get('date') or {}).get('date') or '')
    t = ((game.get('date') or {}).get('time') or '00:00')
    if not d:
        return None
    try:
        return pd.Timestamp(f'{d}T{t}', tz='UTC').tz_convert(MANAUS)
    except Exception:
        return None


def _game_rows(data):
    rows = []
    for item in data.get('response', []) or []:
        game = item.get('game') or {}
        teams = item.get('teams') or {}
        home = teams.get('home') or {}
        away = teams.get('away') or {}
        scores = item.get('scores') or {}
        hs = (scores.get('home') or {}).get('total')
        aws = (scores.get('away') or {}).get('total')
        dt = _game_datetime(game)
        status = game.get('status') or {}
        rows.append({
            'game_id': game.get('id'),
            'team_home_id': home.get('id'),
            'team_away_id': away.get('id'),
            'Data': dt.strftime('%d/%m/%Y') if dt is not None else game.get('date',{}).get('date','—'),
            'Hora (Manaus)': dt.strftime('%H:%M') if dt is not None else '—',
            'Casa': home.get('name') or '—',
            'Fora': away.get('name') or '—',
            'Placar': f'{hs} x {aws}' if hs is not None and aws is not None else '—',
            'Status': status.get('long') or status.get('short') or 'Scheduled',
            '_datetime': dt,
            '_raw': item,
        })
    return rows


def _load_season_games():
    data = api_get('games', {'league': LEAGUE_NFL, 'season': SEASON})
    return _game_rows(data)


def scoreboard(start: date, end: date):
    if end < start:
        return []
    # Uma chamada de temporada é preferível a uma chamada por dia: preserva a quota do plano gratuito.
    rows = _load_season_games()
    return [r for r in rows if r.get('_datetime') is not None and start <= r['_datetime'].date() <= end]


def team_schedule(team_code, start: date, end: date):
    code = str(team_code or '').upper()
    rows = scoreboard(start, end)
    out = []
    for r in rows:
        home_code = _abbr(r['Casa'])
        away_code = _abbr(r['Fora'])
        if code not in (home_code, away_code):
            continue
        out.append({k:v for k,v in r.items() if not k.startswith('_')})
    return sorted(out, key=lambda x: (x['Data'], x['Hora (Manaus)']))


def _abbr(name):
    for full, code in NFL_TEAMS.items():
        if str(name).casefold() == full.casefold():
            return code
    return ''


def _find_game(event_id):
    data = api_get('games', {'id': event_id})
    rows = _game_rows(data)
    if not rows:
        raise RuntimeError(f'Partida NFL {event_id} não encontrada.')
    return rows[0]['_raw']


def summary(event_id):
    game = _find_game(event_id)
    return api_get('games/statistics/teams', {'id': event_id}), api_get('games/statistics/players', {'id': event_id}), game


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, str):
            s = value.replace('%','').replace(',','').strip()
            if '-' in s and s.count('-') == 1:
                a,b = s.split('-',1)
                if a.strip().isdigit() and b.strip().isdigit():
                    return float(a)
            return float(s)
        return float(value)
    except (TypeError, ValueError):
        return None


def _flatten_stats(obj, prefix=''):
    out = {}
    if isinstance(obj, dict):
        for k,v in obj.items():
            key = f'{prefix}_{k}' if prefix else str(k)
            if isinstance(v, dict): out.update(_flatten_stats(v, key))
            elif isinstance(v, list):
                for i,item in enumerate(v): out.update(_flatten_stats(item, f'{key}_{i}'))
            else: out[key] = v
    return out


def parse_team_stats(data):
    rows = []
    for item in data.get('response', []) or []:
        team = item.get('team') or {}
        stats = item.get('statistics') or {}
        flat = _flatten_stats(stats)
        row = {'Equipe': team.get('name') or '—'}
        aliases = {
            'First Downs':'first_downs_total', 'First Downs Pass':'first_downs_passing', 'First Downs Rush':'first_downs_rushing',
            'Third Down':'first_downs_third_down_efficiency', 'Fourth Down':'first_downs_fourth_down_efficiency',
            'Plays':'plays_total', 'Total Yards':'yards_total', 'Yards/Play':'yards_per_play',
            'Passing':'passing_total', 'Passing Yards':'passing_yards', 'Completions':'passing_comp_att',
            'Rushing':'rushings_total', 'Rushing Yards':'rushings_yards', 'Yards/Rush':'rushings_yards_per_rush',
            'Red Zone':'red_zone', 'Penalidades':'penalties_total', 'Turnovers':'turnovers_total',
            'Fumbles Recovered':'fumbles_recovered', 'Interceptions':'interceptions', 'Sacks':'sacks',
            'Safeties':'safeties', 'Pontos contra':'points_against', 'Posse':'possession'
        }
        for label,key in aliases.items():
            val = flat.get(key)
            if val is None:
                # tolera pequenas diferenças de nomenclatura da API sem transformar ausência em zero.
                candidates = [v for k,v in flat.items() if k.endswith('_'+key) or k == key]
                val = candidates[0] if candidates else None
            row[label] = val
        rows.append(row)
    return rows


def _player_group_rows(data):
    for item in data.get('response', []) or []:
        team = item.get('team') or {}
        group = item.get('group') or item.get('type') or 'Estatísticas'
        players = item.get('players') or []
        if isinstance(players, dict):
            players = [players]
        yield team, group, players


def parse_players(data):
    rows = []
    for team, group, players in _player_group_rows(data):
        for item in players:
            p = item.get('player') or {}
            stats = item.get('statistics') or {}
            if isinstance(stats, list):
                merged = {}
                for s in stats: merged.update(s if isinstance(s,dict) else {})
                stats = merged
            flat = _flatten_stats(stats)
            row = {'Equipe': team.get('name') or '—','Jogador': p.get('name') or p.get('displayName') or '—','Posição': p.get('position') or group,'Grupo': group}
            for k,v in flat.items():
                if k and v is not None:
                    row[k] = v
            rows.append(row)
    return rows


def recent_team_games(team_code, n=5):
    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=220)
    rows = team_schedule(team_code, start, end)
    finished = [r for r in rows if r.get('Placar') != '—' and str(r.get('Status','')).lower() in ('finished','aot','ft') or r.get('Placar') != '—']
    return finished[-n:]


def team_averages(team_code, n=5):
    games = recent_team_games(team_code, n)
    # Mantemos o cálculo conservador: cada partida requer seu box score de equipes.
    all_rows = []
    for g in games:
        try:
            team_data, _, _ = summary(g['game_id'])
            all_rows.extend(parse_team_stats(team_data))
        except Exception:
            continue
    target = next((r for r in all_rows if _abbr(r.get('Equipe','')) == str(team_code).upper()), None)
    if not target:
        # Alguns nomes podem não coincidir exatamente; usa a primeira linha somente se houver uma equipe.
        target = all_rows[0] if len(all_rows) == 1 else None
    avg = {}
    if target:
        for k,v in target.items():
            if k == 'Equipe': continue
            nval = _num(v)
            if nval is not None: avg[k] = nval
    return games, avg
