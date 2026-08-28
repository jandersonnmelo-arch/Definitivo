import re
import threading
import time
import unicodedata
from collections import deque
from datetime import datetime, timezone

import streamlit as st

from .base import FootballProvider
from core.http_cache import get_json

BASE = 'https://api.dadosfutebol.com.br/v1'

# Limite interno conservador: a API Free informa 100 req/dia.
# Mantemos margem para testes manuais e outras operações.
DAILY_LIMIT = 80
MIN_INTERVAL_SECONDS = 1.5

_lock = threading.Lock()
_recent_calls = deque()
_day_calls = {}


def _token():
    try:
        block = st.secrets.get('dados_futebol')
        if block:
            for key in ('token', 'key', 'api_key'):
                value = block.get(key)
                if value:
                    return str(value)
        value = st.secrets.get('DADOS_FUTEBOL_API_KEY')
        if value:
            return str(value)
    except Exception:
        pass
    return None


def _norm(value):
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')


def _records(obj):
    if isinstance(obj, list):
        return [x for item in obj for x in _records(item)]
    if isinstance(obj, dict):
        out = [obj]
        for value in obj.values():
            if isinstance(value, (dict, list)):
                out.extend(_records(value))
        return out
    return []


def _id(obj, *keys):
    if not isinstance(obj, dict):
        return None
    for key in keys:
        value = obj.get(key)
        if value is not None:
            return value
    return None


def _team(value):
    if not isinstance(value, dict):
        return {'id': None, 'name': str(value or '')}
    return {
        'id': _id(value, 'id', 'time_id', 'team_id', 'clube_id'),
        'name': value.get('nome') or value.get('nome_popular') or value.get('name') or value.get('apelido') or '',
        'short': value.get('sigla') or value.get('abreviacao') or value.get('short_name'),
    }


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace('%', '').replace(',', '.')
    try:
        return float(text)
    except Exception:
        return None


def _first(obj, aliases):
    if not isinstance(obj, dict):
        return None
    normalized = {_norm(k): v for k, v in obj.items()}
    for alias in aliases:
        key = _norm(alias)
        if key in normalized and normalized[key] is not None:
            return normalized[key]
    return None


MATCH_ALIASES = {
    'goals': ('gols', 'goals', 'gol', 'placar'),
    'shots': ('finalizacoes', 'finalizacoes_totais', 'chutes', 'remates', 'shots', 'total_shots'),
    'shots_on_target': ('finalizacoes_no_alvo', 'finalizacoes_no_gol', 'finalizacoes_certas', 'chutes_no_alvo', 'shots_on_target'),
    'woodwork': ('finalizacoes_na_trave', 'na_trave', 'traves', 'woodwork'),
    'effectivetackles': ('desarmes', 'desarmes_totais', 'tackles', 'effective_tackles'),
    'corners': ('escanteios', 'cantos', 'corner_kicks', 'corners'),
    'fouls': ('faltas', 'faltas_cometidas', 'fouls', 'fouls_committed'),
    'saves': ('defesas_do_goleiro', 'defesas', 'defesas_goleiro', 'saves'),
    'player_throws': ('laterais', 'arremessos_laterais', 'throw_ins', 'throws'),
    'yellow_cards': ('cartoes_amarelos', 'cartao_amarelo', 'yellow_cards'),
    'red_cards': ('cartoes_vermelhos', 'cartao_vermelho', 'red_cards'),
    'offsides': ('impedimentos', 'offside', 'offsides'),
    'goal_kicks': ('tiros_de_meta', 'tiro_de_meta', 'goal_kicks'),
    'passes_completed': ('passes_certos', 'passes_completos', 'passes_precisos', 'passes_acertados', 'passes_accurate', 'passes_completed'),
}

PLAYER_ALIASES = {
    'goals': ('gols', 'gol', 'goals', 'goals_scored'),
    'assists': ('assistencias', 'assistencia', 'assists', 'goal_assists'),
    'shots': ('finalizacoes', 'chutes', 'shots', 'total_shots'),
    'shots_on_target': ('finalizacoes_no_alvo', 'finalizacoes_certas', 'chutes_no_alvo', 'shots_on_target'),
    'passes_completed': ('passes_certos', 'passes_completos', 'passes_precisos', 'passes_acertados', 'passes_completed'),
    'tackles': ('desarmes', 'desarmes_totais', 'tackles', 'effective_tackles'),
    'tackles_won': ('desarmes_ganhos', 'desarmes_certos', 'tackles_won', 'successful_tackles'),
    'fouls': ('faltas_cometidas', 'faltas', 'fouls_committed'),
    'was_fouled': ('faltas_sofridas', 'sofridas', 'was_fouled', 'fouled'),
    'yellow_cards': ('cartoes_amarelos', 'cartao_amarelo', 'yellow_cards'),
    'red_cards': ('cartoes_vermelhos', 'cartao_vermelho', 'red_cards'),
}


def _metric_from_dict(obj, aliases):
    value = _first(obj, aliases)
    if value is not None and not isinstance(value, (dict, list)):
        return _number(value)
    return None


def _match_datetime(item):
    value = _first(item, ('data_hora_realizacao', 'data_hora', 'data_realizacao', 'inicio', 'datetime', 'start_time', 'date'))
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    text = str(value).strip().replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        for fmt in ('%d/%m/%Y %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _status(item):
    text = _norm(_first(item, ('status', 'situacao', 'estado', 'status_nome')))
    if any(x in text for x in ('encerr', 'final', 'fim')):
        return 'FINISHED'
    if any(x in text for x in ('andamento', 'ao_vivo', 'live')):
        return 'LIVE'
    if any(x in text for x in ('adiado', 'cancel')):
        return 'POSTPONED'
    return 'SCHEDULED'


def _find_match_records(data):
    found = []
    seen = set()
    for item in _records(data):
        home = item.get('time_mandante') or item.get('mandante') or item.get('home')
        away = item.get('time_visitante') or item.get('visitante') or item.get('away')
        mid = _id(item, 'id', 'partida_id', 'match_id', 'jogo_id')
        dt = _match_datetime(item)
        if not (home and away and dt and mid is not None):
            continue
        key = str(mid)
        if key in seen:
            continue
        seen.add(key)
        found.append((item, _team(home), _team(away), dt, mid))
    return found


class DadosFutebolProvider(FootballProvider):
    """Fonte dedicada ao futebol brasileiro, usada como fonte primária da Série B."""

    name = 'Dados Futebol'

    def __init__(self):
        self.token = _token()
        self._championship_id = None

    def available(self):
        return bool(self.token)

    def _wait_slot(self):
        today = datetime.now(timezone.utc).date().isoformat()
        with _lock:
            count = _day_calls.get(today, 0)
            if count >= DAILY_LIMIT:
                raise RuntimeError(f'Limite interno da Dados Futebol atingido: {DAILY_LIMIT} chamadas/dia.')
            now = time.monotonic()
            while _recent_calls and now - _recent_calls[0] >= 60:
                _recent_calls.popleft()
            if _recent_calls:
                elapsed = now - _recent_calls[-1]
                if elapsed < MIN_INTERVAL_SECONDS:
                    time.sleep(MIN_INTERVAL_SECONDS - elapsed)
            _recent_calls.append(time.monotonic())
            _day_calls[today] = count + 1

    def _get(self, path):
        if not self.token:
            raise RuntimeError('chave [dados_futebol] não configurada')
        self._wait_slot()
        return get_json(
            BASE + path,
            headers={'Authorization': f'Bearer {self.token}', 'Accept': 'application/json'},
            provider=self.name,
        )

    def _find_championship(self):
        if self._championship_id is not None:
            return self._championship_id
        data = self._get('/campeonatos')
        ranked = []
        for item in _records(data):
            cid = _id(item, 'id', 'campeonato_id')
            name = _first(item, ('nome', 'nome_popular', 'name', 'campeonato_nome')) or ''
            season = _first(item, ('temporada', 'season', 'ano'))
            text = _norm(name)
            if cid is None or 'serie_b' not in text and 'brasileirao_b' not in text and 'brasileiro_b' not in text:
                continue
            score = 100 + (50 if str(season) == '2026' else 0)
            ranked.append((score, cid, name, season))
        if not ranked:
            raise RuntimeError('Brasileirão Série B 2026 não encontrado em Dados Futebol.')
        ranked.sort(reverse=True)
        self._championship_id = ranked[0][1]
        return self._championship_id

    def matches(self, date_from, date_to, competition=None):
        cid = self._find_championship()
        data = self._get(f'/campeonatos/{cid}/partidas')
        start = datetime.fromisoformat(date_from).date()
        end = datetime.fromisoformat(date_to).date()
        out = []
        for item, home, away, dt, mid in _find_match_records(data):
            local = dt.astimezone(timezone.utc).date()
            if not (start <= local <= end):
                continue
            out.append({
                'id': f'df:{mid}',
                'provider_match_id': str(mid),
                'sport': 'Futebol',
                'competition': 'Campeonato Brasileiro Série B',
                'season': '2026',
                'start_time': dt.isoformat(),
                'status': _status(item),
                'minute': _first(item, ('minuto', 'minute')),
                'home_id': home['id'], 'home_name': home['name'], 'home_short': home['short'],
                'away_id': away['id'], 'away_name': away['name'], 'away_short': away['short'],
                'home_score': _first(item, ('placar_mandante', 'mandante_gols', 'home_score')),
                'away_score': _first(item, ('placar_visitante', 'visitante_gols', 'away_score')),
                'source': self.name,
            })
        return out

    def _team_stats(self, detail, match):
        rows = []
        candidates = []
        if isinstance(detail, dict):
            for key in ('estatisticas', 'stats', 'estatisticas_times', 'team_stats'):
                value = detail.get(key)
                if value is not None:
                    candidates.extend(value if isinstance(value, list) else [value])
        for item in _records(detail):
            home = item.get('mandante') or item.get('time_mandante') or item.get('home')
            away = item.get('visitante') or item.get('time_visitante') or item.get('away')
            if home or away:
                candidates.append(item)
        for item in candidates:
            team = item.get('time') or item.get('equipe') or item.get('team') or item.get('mandante') or item.get('home')
            t = _team(team) if isinstance(team, dict) else None
            if not t or t['id'] is None:
                continue
            for metric, aliases in MATCH_ALIASES.items():
                value = _metric_from_dict(item, aliases)
                if value is not None:
                    rows.append({'team_id': t['id'], 'metric': metric, 'value': value, 'source': self.name})
        # Alguns formatos usam {metricas:[{nome,mandante,visitante}]}
        for item in _records(detail):
            name = _first(item, ('nome', 'metrica', 'metric', 'titulo', 'title'))
            if not name:
                continue
            key = _norm(name)
            metric = None
            for canonical, aliases in MATCH_ALIASES.items():
                if key in {_norm(x) for x in aliases}:
                    metric = canonical; break
            if not metric:
                continue
            home_value = _number(_first(item, ('mandante', 'casa', 'home', 'valor_mandante')))
            away_value = _number(_first(item, ('visitante', 'fora', 'away', 'valor_visitante')))
            if home_value is not None: rows.append({'team_id': match.get('home_id'), 'metric': metric, 'value': home_value, 'source': self.name})
            if away_value is not None: rows.append({'team_id': match.get('away_id'), 'metric': metric, 'value': away_value, 'source': self.name})
        return rows

    def _players_from_lineup(self, lineup, match):
        players = []
        groups = []
        if isinstance(lineup, dict):
            for key in ('mandante', 'visitante', 'home', 'away', 'home_team', 'away_team', 'escalacao_mandante', 'escalacao_visitante'):
                if key in lineup: groups.append((key, lineup[key]))
        if not groups:
            groups = [('all', lineup)]
        for side, group in groups:
            team_id = match.get('home_id') if 'home' in side or 'mandante' in side else match.get('away_id')
            team_name = match.get('home_name') if 'home' in side or 'mandante' in side else match.get('away_name')
            entries = []
            if isinstance(group, list): entries = group
            elif isinstance(group, dict):
                for key in ('titulares', 'reservas', 'jogadores', 'players', 'atletas', 'starters', 'substitutes'):
                    if isinstance(group.get(key), list): entries.extend(group[key])
            for p in entries:
                if not isinstance(p, dict): continue
                pid = _id(p, 'id', 'jogador_id', 'player_id', 'atleta_id')
                name = _first(p, ('nome', 'name', 'nome_completo', 'jogador_nome'))
                if pid is None or not name: continue
                position = _first(p, ('posicao', 'posição', 'position', 'sigla_posicao', 'position_abbreviation'))
                players.append({'id': pid, 'name': name, 'position': position, 'team_id': team_id or _id(p, 'team_id', 'time_id'), 'team_name': team_name, 'source': self.name})
        return players

    def _player_stats(self, detail, players, match):
        by_id = {str(p['id']): p for p in players}
        rows = []
        for item in _records(detail):
            pid = _id(item, 'jogador_id', 'player_id', 'atleta_id', 'id')
            if pid is None or str(pid) not in by_id:
                continue
            # Evita interpretar objetos de cadastro do atleta como estatística.
            for metric, aliases in PLAYER_ALIASES.items():
                value = _metric_from_dict(item, aliases)
                if value is not None:
                    p = by_id[str(pid)]
                    rows.append({'player_id': pid, 'metric': metric, 'value': value, 'source': self.name, 'team_id': p.get('team_id'), 'team_name': p.get('team_name')})
        return rows

    def match_details(self, match_id):
        mid = str(match_id)
        if mid.startswith('df:'): mid = mid[3:]
        detail = self._get(f'/partidas/{mid}/estatisticas')
        try:
            lineup = self._get(f'/partidas/{mid}/escalacao')
        except Exception:
            try:
                lineup = self._get(f'/partidas/{mid}/escalação')
            except Exception:
                lineup = {}
        # Recupera placar/nomes se o endpoint de estatísticas não os trouxer.
        match_stub = {'home_id': None, 'away_id': None, 'home_name': '', 'away_name': ''}
        for item, home, away, dt, _ in _find_match_records(detail):
            match_stub.update({'home_id': home['id'], 'away_id': away['id'], 'home_name': home['name'], 'away_name': away['name']})
            break
        players = self._players_from_lineup(lineup, match_stub)
        stats = self._team_stats(detail, match_stub)
        pstats = self._player_stats(detail, players, match_stub)
        return {'stats': stats, 'players': players, 'player_stats': pstats}
