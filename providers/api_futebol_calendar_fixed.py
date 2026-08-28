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

    return datetime.combine(d, time(12, 0), tzinfo=MANAUS)


class ApiFutebolCalendarProviderFixed(ApiFutebolCalendarProvider):
    """Série B via API Futebol usando o detalhe oficial para data/hora."""

    name = 'API-Futebol'

    def _extract_detail_datetime(self, detail, home_name, away_name):
        """Busca a data/hora oficial no detalhe da partida."""
        candidates = self._extract_matches(detail)
        for item in candidates:
            home = _team(item.get('mandante') or item.get('home') or item.get('time_mandante') or item.get('equipe_mandante'))
            away = _team(item.get('visitante') or item.get('away') or item.get('time_visitante') or item.get('equipe_visitante'))
            if home_name and away_name and home['name'] != home_name and away['name'] != away_name:
                continue
            dt = _parse_api_match_datetime(item)
            if dt is not None:
                return dt, item

        def walk(value):
            if isinstance(value, dict):
                keys = {str(k).lower() for k in value.keys()}
                if keys.intersection({'data_realizacao', 'data_hora', 'horario_realizacao', 'horario', 'hora_realizacao', 'date', 'datetime'}):
                    dt = _parse_api_match_datetime(value)
                    if dt is not None:
                        return dt, value
                for child in value.values():
                    result = walk(child)
                    if result:
                        return result
            elif isinstance(value, list):
                for child in value:
                    result = walk(child)
                    if result:
                        return result
            return None

        return walk(detail) or (None, None)

    def matches(self, date_from, date_to, competition=None):
        championship = self._find_championship()
        phase = self._find_phase(championship)
        raw = self._phase_matches(championship, phase)
        start = datetime.fromisoformat(date_from).date()
        end = datetime.fromisoformat(date_to).date()

        parsed = []
        invalid = 0
        candidate_rounds = set()

        for item in raw:
            home = _team(item.get('mandante') or item.get('home') or item.get('time_mandante') or item.get('equipe_mandante'))
            away = _team(item.get('visitante') or item.get('away') or item.get('time_visitante') or item.get('equipe_visitante'))
            dt = _parse_api_match_datetime(item)
            if dt is None or not home['name'] or not away['name']:
                invalid += 1
                continue

            round_value = item.get('rodada') or item.get('round') or item.get('rodada_id') or item.get('round_id')
            parsed.append((item, home, away, dt, round_value))
            if start <= dt.astimezone(MANAUS).date() <= end and round_value is not None:
                candidate_rounds.add(str(round_value))

        # O resumo da fase pode conter a data/hora antiga da tabela básica.
        # Para as rodadas candidatas, consulta o detalhe oficial de cada partida.
        detail_checked = 0
        detail_corrected = 0
        exact = {}

        for item, home, away, phase_dt, round_value in parsed:
            if round_value is None or str(round_value) not in candidate_rounds:
                continue

            mid = _id(item, ('partida_id', 'jogo_id', 'match_id', 'id'))
            if mid is None:
                continue

            try:
                detail = self._get(f'/partidas/{mid}')
                exact_dt, _ = self._extract_detail_datetime(detail, home['name'], away['name'])
                detail_checked += 1

                if exact_dt is not None:
                    exact[str(mid)] = exact_dt
                    if exact_dt.astimezone(MANAUS).date() != phase_dt.astimezone(MANAUS).date():
                        detail_corrected += 1
                        add_diagnostic(
                            'coleta',
                            'INFO',
                            f'Série B: data corrigida {home["name"]} x {away["name"]}: fase={phase_dt.isoformat()} detalhe={exact_dt.isoformat()}',
                            self.name,
                            str(mid),
                        )
            except Exception as exc:
                add_diagnostic(
                    'coleta',
                    'WARNING',
                    f'Série B: detalhe {mid} indisponível; usando data da fase: {exc}',
                    self.name,
                    str(mid),
                )

        out, seen = [], set()

        for item, home, away, phase_dt, round_value in parsed:
            mid = str(_id(item, ('partida_id', 'jogo_id', 'match_id', 'id')) or f"{home['id']}-{away['id']}-{phase_dt.isoformat()}")
            dt = exact.get(mid, phase_dt)
            local_date = dt.astimezone(MANAUS).date()

            if not (start <= local_date <= end) or mid in seen:
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

        add_diagnostic(
            'coleta',
            'INFO',
            f'Série B DATA FIX: brutas={len(raw)}; válidas={len(parsed)}; inválidas={invalid}; rodadas candidatas={len(candidate_rounds)}; detalhes consultados={detail_checked}; datas corrigidas={detail_corrected}',
            self.name,
        )
        add_diagnostic('coleta', 'INFO', f'Série B DATA FIX: partidas no período={len(out)}', self.name)
        return out
