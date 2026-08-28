from datetime import datetime, date, time
from zoneinfo import ZoneInfo

from .api_futebol_calendar import ApiFutebolCalendarProvider
from .api_futebol_calendar import _team, _id, _norm
from core.db import add_diagnostic

MANAUS = ZoneInfo('America/Manaus')
SAO_PAULO = ZoneInfo('America/Sao_Paulo')
UTC = ZoneInfo('UTC')


def _date_only(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value or '').strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except Exception:
            pass
    return None


def _parse_api_match_datetime(item):
    # Primeiro tenta campos que já contêm data + hora.
    for key in ('data_hora', 'datetime', 'start_time', 'date'):
        value = item.get(key)
        if value and (':' in str(value) or 'T' in str(value)):
            text = str(value).strip().replace('Z', '+00:00')
            try:
                dt = datetime.fromisoformat(text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=SAO_PAULO)
                return dt
            except Exception:
                pass

    raw_date = item.get('data_realizacao') or item.get('data')
    raw_time = (
        item.get('hora_realizacao')
        or item.get('horario_realizacao')
        or item.get('horario')
        or item.get('hora')
        or item.get('hora_inicio')
        or item.get('horario_inicio')
        or item.get('inicio')
    )
    d = _date_only(raw_date)
    if not d:
        return None

    if raw_time:
        text = str(raw_time).strip()
        for fmt in ('%H:%M', '%H:%M:%S'):
            try:
                t = datetime.strptime(text[:8], fmt).time()
                return datetime.combine(d, t, tzinfo=SAO_PAULO)
            except Exception:
                pass

    # O endpoint da fase pode fornecer somente a data do jogo.
    # Meio-dia em Manaus é usado apenas como fallback técnico para impedir
    # que uma data sem horário seja deslocada para o dia anterior.
    return datetime.combine(d, time(12, 0), tzinfo=MANAUS)


class ApiFutebolCalendarProviderFixed(ApiFutebolCalendarProvider):
    """Série B via API Futebol com tratamento correto de datas sem horário."""

    name = 'API-Futebol'

    def matches(self, date_from, date_to, competition=None):
        championship = self._find_championship()
        phase = self._find_phase(championship)
        raw = self._phase_matches(championship, phase)
        start = datetime.fromisoformat(date_from).date()
        end = datetime.fromisoformat(date_to).date()

        out, seen = [], set()
        valid = 0
        invalid = 0
        examples = []

        for item in raw:
            home = _team(item.get('mandante') or item.get('home') or item.get('time_mandante') or item.get('equipe_mandante'))
            away = _team(item.get('visitante') or item.get('away') or item.get('time_visitante') or item.get('equipe_visitante'))
            dt = _parse_api_match_datetime(item)

            if dt is None or not home['name'] or not away['name']:
                invalid += 1
                continue

            valid += 1
            if len(examples) < 5:
                examples.append(f"{home['name']} x {away['name']} = {dt.isoformat()}")

            local_date = dt.astimezone(MANAUS).date()
            if not (start <= local_date <= end):
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
                'start_time': dt.astimezone(UTC).isoformat(),
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

        add_diagnostic('coleta', 'INFO', f"Série B FIX: datas válidas={valid}; inválidas={invalid}; exemplos={' | '.join(examples) or '—'}", self.name)
        add_diagnostic('coleta', 'INFO', f'Série B FIX: partidas no período={len(out)}', self.name)
        return out
