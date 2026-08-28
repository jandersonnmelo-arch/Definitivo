# Backup da versão anterior de providers/api_futebol_calendar.py
# Mantido para rollback.

import re
import unicodedata
from datetime import datetime

import streamlit as st

from .base import FootballProvider
from core.http_cache import get_json

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


def _items(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ('campeonatos', 'fases', 'rodadas', 'partidas', 'jogos', 'results', 'data'):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


class ApiFutebolCalendarProvider(FootballProvider):
    name = 'API-Futebol'

    def __init__(self):
        self.token = _token()

    def available(self):
        return bool(self.token)

    def _get(self, path):
        if not self.token:
            raise RuntimeError('chave [api_futebol] não configurada')
        return get_json(BASE + path, headers={'Authorization': f'Bearer {self.token}'}, provider=self.name)

    def _find_championship(self):
        data = self._get('/campeonatos')
        candidates = _items(data)
        ranked = []
        for c in candidates:
            name = c.get('nome') or c.get('nome_popular') or c.get('name') or ''
            season = c.get('temporada') or c.get('ano') or c.get('season') or ''
            text = _norm(name)
            score = 0
            if 'serie b' in text or 'brasileirao b' in text or 'brasileiro b' in text: score += 100
            if 'brasil' in text: score += 10
            if str(season) == '2026': score += 50
            cid = c.get('campeonato_id') or c.get('id')
            if cid is not None and score: ranked.append((score, c))
        if not ranked: raise RuntimeError('Campeonato Brasileiro Série B 2026 não encontrado na API Futebol')
        ranked.sort(key=lambda x: x[0], reverse=True)
        return ranked[0][1]

    def _find_phase(self, championship):
        cid = championship.get('campeonato_id') or championship.get('id')
        data = self._get(f'/campeonatos/{cid}/fases')
        phases = _items(data)
        if not phases:
            detail = self._get(f'/campeonatos/{cid}')
            phases = _items(detail)
        if not phases: raise RuntimeError('Fases da Série B não encontradas')
        ranked = []
        for phase in phases:
            name = _norm(phase.get('nome') or phase.get('name'))
            status = _norm(phase.get('status'))
            fid = phase.get('fase_id') or phase.get('id')
            if fid is None: continue
            score = 0
            if 'andamento' in status or 'em andamento' in status: score += 100
            if 'unica' in name or 'primeira' in name or 'fase unica' in name: score += 20
            ranked.append((score, phase))
        if not ranked: raise RuntimeError('Nenhuma fase válida encontrada para a Série B')
        ranked.sort(key=lambda x: x[0], reverse=True)
        return ranked[0][1]

    def _extract_matches(self, obj):
        found = []
        if isinstance(obj, list):
            for item in obj: found.extend(self._extract_matches(item))
            return found
        if not isinstance(obj, dict): return found
        home = obj.get('mandante') or obj.get('home') or obj.get('time_mandante')
        away = obj.get('visitante') or obj.get('away') or obj.get('time_visitante')
        date_value = obj.get('data_realizacao') or obj.get('data') or obj.get('start_time') or obj.get('date')
        if (isinstance(home, dict) or isinstance(away, dict)) and date_value: found.append(obj)
        for key, value in obj.items():
            if key not in ('mandante', 'visitante', 'home', 'away', 'time_mandante', 'time_visitante'):
                found.extend(self._extract_matches(value))
        return found

    def _phase_matches(self, championship, phase):
        cid = championship.get('campeonato_id') or championship.get('id')
        fid = phase.get('fase_id') or phase.get('id')
        detail = self._get(f'/campeonatos/{cid}/fases/{fid}')
        matches = self._extract_matches(detail)
        if matches: return matches
        rounds = _items(detail)
        for item in rounds:
            rid = item.get('rodada_id') or item.get('id') if isinstance(item, dict) else None
            if rid is None: continue
            try:
                rd = self._get(f'/campeonatos/{cid}/fases/{fid}/rodadas/{rid}')
                matches.extend(self._extract_matches(rd))
            except Exception: continue
        return matches

    @staticmethod
    def _team(value):
        if not isinstance(value, dict): return {'id': None, 'name': str(value or '')}
        return {'id': value.get('time_id') or value.get('id') or value.get('team_id'), 'name': value.get('nome_popular') or value.get('nome') or value.get('name') or ''}

    def matches(self, date_from, date_to, competition=None):
        championship = self._find_championship()
        phase = self._find_phase(championship)
        raw = self._phase_matches(championship, phase)
        start = datetime.fromisoformat(date_from).date(); end = datetime.fromisoformat(date_to).date()
        out, seen = [], set()
        for item in raw:
            home = self._team(item.get('mandante') or item.get('home') or item.get('time_mandante'))
            away = self._team(item.get('visitante') or item.get('away') or item.get('time_visitante'))
            date_value = item.get('data_realizacao') or item.get('data') or item.get('start_time') or item.get('date')
            if not date_value or not home['name'] or not away['name']: continue
            try: dt = datetime.fromisoformat(str(date_value).replace('Z', '+00:00'))
            except Exception: continue
            if not (start <= dt.date() <= end): continue
            mid = str(item.get('partida_id') or item.get('id') or f"{home['id']}-{away['id']}-{dt.isoformat()}")
            if mid in seen: continue
            status = _norm(item.get('status') or item.get('situacao') or '')
            if any(x in status for x in ('final', 'encerr', 'fim')): normalized_status = 'FINISHED'
            elif any(x in status for x in ('andamento', 'ao vivo', 'live')): normalized_status = 'LIVE'
            elif any(x in status for x in ('adiado', 'cancel')): normalized_status = 'POSTPONED'
            else: normalized_status = 'SCHEDULED'
            out.append({'id': mid, 'provider_match_id': mid, 'sport': 'Futebol', 'competition': 'Campeonato Brasileiro Série B', 'season': '2026', 'start_time': dt.isoformat(), 'status': normalized_status, 'minute': None, 'home_id': home['id'], 'home_name': home['name'], 'home_short': None, 'away_id': away['id'], 'away_name': away['name'], 'away_short': None, 'home_score': item.get('placar_mandante') or item.get('home_score'), 'away_score': item.get('placar_visitante') or item.get('away_score'), 'source': self.name})
            seen.add(mid)
        return out
