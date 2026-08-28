import re
import unicodedata
from datetime import datetime

import streamlit as st

from .base import FootballProvider
from core.http_cache import get_json
from core.db import add_diagnostic

BASE = 'https://api.api-futebol.com.br/v1'


def _token():
    try:
        block = st.secrets.get('api_futebol')
        if block:
            for key in ('token', 'key', 'api_key'):
                value = block.get(key)
                if value:
                    return str(value)
    except Exception:
        pass
    return None


def _norm(value):
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()


def _records(obj):
    out = []
    if isinstance(obj, list):
        for item in obj:
            out.extend(_records(item))
    elif isinstance(obj, dict):
        out.append(obj)
        for value in obj.values():
            if isinstance(value, (dict, list)):
                out.extend(_records(value))
    return out


def _top_keys(obj):
    return ', '.join(list(obj.keys())[:15]) if isinstance(obj, dict) else type(obj).__name__


def _id(obj, keys):
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
        'id': _id(value, ('time_id', 'team_id', 'id')),
        'name': value.get('nome_popular') or value.get('nome') or value.get('name') or value.get('apelido') or '',
    }


def _parse_datetime(value):
    """Aceita ISO e os formatos de data usados pela API Futebol."""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).strip()
    for candidate in (text, text.replace('Z', '+00:00')):
        try:
            return datetime.fromisoformat(candidate)
        except Exception:
            pass
    for fmt in ('%d/%m/%Y %H:%M', '%d/%m/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass
    return None


class ApiFutebolCalendarProvider(FootballProvider):
    """Calendário da API Futebol, usado exclusivamente para a Série B."""

    name = 'API-Futebol'

    def __init__(self):
        self.token = _token()

    def available(self):
        return bool(self.token)

    def _get(self, path):
        if not self.token:
            raise RuntimeError('chave [api_futebol] não configurada')
        return get_json(
            BASE + path,
            headers={'Authorization': f'Bearer {self.token}', 'Accept': 'application/json'},
            provider=self.name,
        )

    def _find_championship(self):
        data = self._get('/campeonatos')
        records = _records(data)
        ranked = []
        for c in records:
            cid = _id(c, ('campeonato_id', 'id'))
            name = c.get('nome') or c.get('nome_popular') or c.get('name') or c.get('nome_completo') or ''
            season = c.get('temporada') or c.get('ano') or c.get('season') or c.get('temporada_id') or ''
            text = _norm(name)
            if cid is None:
                continue
            score = 0
            if 'serie b' in text or 'brasileirao b' in text or 'brasileiro b' in text:
                score += 100
            if 'brasil' in text:
                score += 10
            if str(season) == '2026':
                score += 50
            if score:
                ranked.append((score, c))
        if not ranked:
            raise RuntimeError(f'Série B 2026 não encontrada. Resposta /campeonatos: {_top_keys(data)}')
        ranked.sort(key=lambda x: x[0], reverse=True)
        championship = ranked[0][1]
        add_diagnostic('coleta', 'INFO', f'Série B: campeonato encontrado id={_id(championship, ("campeonato_id", "id"))} nome={championship.get("nome") or championship.get("nome_popular") or championship.get("name")}', self.name)
        return championship

    def _find_phase(self, championship):
        cid = _id(championship, ('campeonato_id', 'id'))
        data = self._get(f'/campeonatos/{cid}/fases')
        records = _records(data)
        phases = []
        for p in records:
            fid = _id(p, ('fase_id', 'id'))
            name = p.get('nome') or p.get('name') or p.get('descricao') or ''
            if fid is None or not (name or p.get('status') or p.get('rodadas') or p.get('rodada')):
                continue
            text = _norm(name)
            score = 0
            status = _norm(p.get('status') or p.get('situacao') or '')
            if 'andamento' in status or 'em andamento' in status:
                score += 100
            if 'unica' in text or 'primeira' in text or 'fase unica' in text:
                score += 20
            phases.append((score, p))
        if not phases:
            raise RuntimeError(f'Fases da Série B não encontradas. Resposta /fases: {_top_keys(data)}')
        phases.sort(key=lambda x: x[0], reverse=True)
        phase = phases[0][1]
        add_diagnostic('coleta', 'INFO', f'Série B: fase encontrada id={_id(phase, ("fase_id", "id"))} nome={phase.get("nome") or phase.get("name")}', self.name)
        return phase

    def _extract_matches(self, obj):
        found = []
        seen = set()
        def walk(value):
            if isinstance(value, list):
                for item in value:
                    walk(item)
                return
            if not isinstance(value, dict):
                return
            home = value.get('mandante') or value.get('home') or value.get('time_mandante') or value.get('equipe_mandante')
            away = value.get('visitante') or value.get('away') or value.get('time_visitante') or value.get('equipe_visitante')
            date_value = value.get('data_realizacao') or value.get('data_hora') or value.get('data') or value.get('start_time') or value.get('datetime') or value.get('date')
            match_id = _id(value, ('partida_id', 'jogo_id', 'match_id'))
            if (isinstance(home, dict) or isinstance(away, dict)) and date_value:
                key = str(match_id or f'{date_value}|{home}|{away}')
                if key not in seen:
                    found.append(value)
                    seen.add(key)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        walk(obj)
        return found

    def _phase_matches(self, championship, phase):
        cid = _id(championship, ('campeonato_id', 'id'))
        fid = _id(phase, ('fase_id', 'id'))
        detail = self._get(f'/campeonatos/{cid}/fases/{fid}')
        matches = self._extract_matches(detail)
        if matches:
            return matches
        round_ids = []
        for item in _records(detail):
            rid = _id(item, ('rodada_id', 'id'))
            name = item.get('nome') or item.get('name') or item.get('descricao') or ''
            if rid is not None and ('rodada' in _norm(name) or 'round' in _norm(name) or 'jornada' in _norm(name)):
                if str(rid) not in {str(x) for x in round_ids}:
                    round_ids.append(rid)
        try:
            rounds_data = self._get(f'/campeonatos/{cid}/fases/{fid}/rodadas')
            for item in _records(rounds_data):
                rid = _id(item, ('rodada_id', 'id'))
                if rid is not None and str(rid) not in {str(x) for x in round_ids}:
                    round_ids.append(rid)
        except Exception:
            pass
        add_diagnostic('coleta', 'INFO', f'Série B: fase sem partidas diretas; rodadas identificadas={len(round_ids)}', self.name)
        for rid in round_ids:
            try:
                rd = self._get(f'/campeonatos/{cid}/fases/{fid}/rodadas/{rid}')
                matches.extend(self._extract_matches(rd))
            except Exception as exc:
                add_diagnostic('coleta', 'ERROR', f'Série B: erro na rodada {rid}: {exc}', self.name)
        if not matches:
            try:
                champ_detail = self._get(f'/campeonatos/{cid}')
                matches = self._extract_matches(champ_detail)
            except Exception:
                pass
        return matches

    def matches(self, date_from, date_to, competition=None):
        championship = self._find_championship()
        phase = self._find_phase(championship)
        raw = self._phase_matches(championship, phase)
        add_diagnostic('coleta', 'INFO', f'Série B: partidas brutas encontradas={len(raw)}; período={date_from}→{date_to}', self.name)
        start = datetime.fromisoformat(date_from).date()
        end = datetime.fromisoformat(date_to).date()
        out, seen = [], set()
        for item in raw:
            home = _team(item.get('mandante') or item.get('home') or item.get('time_mandante') or item.get('equipe_mandante'))
            away = _team(item.get('visitante') or item.get('away') or item.get('time_visitante') or item.get('equipe_visitante'))
            date_value = item.get('data_realizacao') or item.get('data_hora') or item.get('data') or item.get('start_time') or item.get('datetime') or item.get('date')
            if not date_value or not home['name'] or not away['name']:
                continue
            dt = _parse_datetime(date_value)
            if dt is None:
                continue
            if not (start <= dt.date() <= end):
                continue
            mid = str(_id(item, ('partida_id', 'jogo_id', 'match_id', 'id')) or f"{home['id']}-{away['id']}-{dt.isoformat()}")
            if mid in seen:
                continue
            status = _norm(item.get('status') or item.get('situacao') or item.get('estado') or '')
            if any(x in status for x in ('final', 'encerr', 'fim')):
                normalized_status = 'FINISHED'
            elif any(x in status for x in ('andamento', 'ao vivo', 'live')):
                normalized_status = 'LIVE'
            elif any(x in status for x in ('adiado', 'cancel')):
                normalized_status = 'POSTPONED'
            else:
                normalized_status = 'SCHEDULED'
            out.append({
                'id': mid,
                'provider_match_id': mid,
                'sport': 'Futebol',
                'competition': 'Campeonato Brasileiro Série B',
                'season': '2026',
                'start_time': dt.isoformat(),
                'status': normalized_status,
                'minute': None,
                'home_id': home['id'],
                'home_name': home['name'],
                'home_short': None,
                'away_id': away['id'],
                'away_name': away['name'],
                'away_short': None,
                'home_score': item.get('placar_mandante') if item.get('placar_mandante') is not None else item.get('home_score'),
                'away_score': item.get('placar_visitante') if item.get('placar_visitante') is not None else item.get('away_score'),
                'source': self.name,
            })
            seen.add(mid)
        add_diagnostic('coleta', 'INFO', f'Série B: partidas no período={len(out)}', self.name)
        return out
