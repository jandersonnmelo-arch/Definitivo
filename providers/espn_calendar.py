from datetime import datetime

from .espn import ESPNProvider
from core.http_cache import get_json
from core.normalizer import normalize_status

BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer'

# O endpoint /all nao garante todas as competicoes. Estas ligas sao consultadas
# explicitamente para cobrir principalmente o futebol brasileiro e CONMEBOL,
# alem das principais ligas que fazem parte do catalogo do aplicativo.
ESPN_CALENDAR_LEAGUES = [
    'all',
    'bra.1',
    'bra.2',
    'bra.copa_do_brazil',
    'bra.camp.paulista',
    'bra.camp.carioca',
    'bra.camp.gaucho',
    'bra.camp.mineiro',
    'bra.copa_do_nordeste',
    'conmebol.libertadores',
    'conmebol.sudamericana',
    'conmebol.recopa',
    'uefa.champions',
    'uefa.europa',
    'uefa.europa.conf',
    'eng.1',
    'esp.1',
    'ger.1',
    'ita.1',
    'fra.1',
    'por.1',
    'ned.1',
    'bel.1',
    'arg.1',
    'usa.1',
    'mex.1',
    'sau.1',
    'tur.1',
    'col.1',
    'jpn.1',
    'kor.1',
]


class ESPNCalendarProvider(ESPNProvider):
    """ESPN dedicada ao calendario, consultando ligas explicitamente."""

    name = 'ESPN'

    def matches(self, date_from, date_to, competition=None):
        out = []
        seen = set()
        start = datetime.fromisoformat(date_from)
        end = datetime.fromisoformat(date_to)
        date_param = f'{start:%Y%m%d}-{end:%Y%m%d}' if start != end else f'{start:%Y%m%d}'

        for league in ESPN_CALENDAR_LEAGUES:
            try:
                data = get_json(
                    f'{BASE}/{league}/scoreboard',
                    {'dates': date_param},
                    provider='ESPN',
                )
            except Exception:
                # Uma liga eventualmente inexistente/sem cobertura nao pode
                # impedir as demais fontes e competicoes de serem coletadas.
                continue

            for x in data.get('events', []):
                event_id = str(x.get('id') or '')
                if not event_id or event_id in seen:
                    continue

                comp = (
                    ((x.get('competitions') or [{}])[0].get('league') or {}).get('name')
                    or ((x.get('season') or {}).get('displayName'))
                )
                if competition and competition.lower() not in str(comp).lower():
                    continue

                c = (x.get('competitions') or [{}])[0]
                teams = c.get('competitors') or []
                home = next((t for t in teams if t.get('homeAway') == 'home'), teams[0] if teams else {})
                away = next((t for t in teams if t.get('homeAway') == 'away'), teams[1] if len(teams) > 1 else {})
                st = x.get('status') or {}
                typ = st.get('type') or {}
                status = normalize_status(
                    typ.get('name') or typ.get('state') or typ.get('description'),
                    typ.get('completed'),
                )

                out.append({
                    'id': event_id,
                    'provider_match_id': event_id,
                    'sport': 'Futebol',
                    'competition': comp,
                    'season': str((x.get('season') or {}).get('year') or ''),
                    'start_time': x.get('date'),
                    'status': status,
                    'minute': self._minute(st, status),
                    'home_id': (home.get('team') or {}).get('id'),
                    'home_name': (home.get('team') or {}).get('displayName') or home.get('displayName', ''),
                    'home_short': (home.get('team') or {}).get('abbreviation'),
                    'away_id': (away.get('team') or {}).get('id'),
                    'away_name': (away.get('team') or {}).get('displayName') or away.get('displayName', ''),
                    'away_short': (away.get('team') or {}).get('abbreviation'),
                    'home_score': self._score(home) if status in ('LIVE', 'PAUSED', 'FINISHED') else None,
                    'away_score': self._score(away) if status in ('LIVE', 'PAUSED', 'FINISHED') else None,
                    'source': self.name,
                })
                seen.add(event_id)

        return out
