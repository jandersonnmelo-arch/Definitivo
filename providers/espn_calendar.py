from datetime import datetime

from .espn import ESPNProvider
from core.competitions import competition_matches, canonical_competition_label
from core.http_cache import get_json
from core.normalizer import normalize_status

BASES = [
    'https://site.api.espn.com/apis/site/v2/sports/soccer',
    'https://site.web.api.espn.com/apis/site/v2/sports/soccer',
]

# Cobertura explícita. Não dependemos do /all, que não garante todas as competições.
ESPN_CALENDAR_LEAGUES = [
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
    'ksa.1',
    'tur.1',
    'col.1',
    'jpn.1',
    'kor.1',
]

# Rótulo canônico do projeto para competições que precisam de cobertura explícita.
LEAGUE_CANONICAL = {
    'bra.1': '🇧🇷 Campeonato Brasileiro Série A',
    'bra.2': '🇧🇷 Campeonato Brasileiro Série B',
    'bra.copa_do_brazil': '🏆 Copa do Brasil',
    'conmebol.libertadores': '🏆 Copa Libertadores',
    'conmebol.sudamericana': '🏆 Copa Sudamericana',
    'conmebol.recopa': '🏆 Copa Sudamericana',
}


class ESPNCalendarProvider(ESPNProvider):
    """ESPN dedicada ao calendário, consultando cada competição explicitamente."""

    name = 'ESPN'

    def _fetch_scoreboard(self, league, date_param):
        params = {
            'dates': date_param,
            'limit': 1000,
            'lang': 'pt-BR',
        }
        last_error = None
        for base in BASES:
            try:
                data = get_json(
                    f'{base}/{league}/scoreboard',
                    params,
                    provider='ESPN',
                )
                if isinstance(data, dict):
                    return data
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        return {}

    @staticmethod
    def _canonical_competition(league, raw_name):
        """Prioriza o slug ESPN para evitar variações de nome/acentuação."""
        fixed = LEAGUE_CANONICAL.get(league)
        if fixed:
            return fixed
        return canonical_competition_label(raw_name)

    @staticmethod
    def _selected_competition_matches(league, raw_name, selected):
        if not selected:
            return True
        canonical = LEAGUE_CANONICAL.get(league)
        if canonical and canonical in selected:
            return True
        return competition_matches(raw_name, selected)

    def matches(self, date_from, date_to, competition=None):
        out = []
        seen = set()
        start = datetime.fromisoformat(date_from)
        end = datetime.fromisoformat(date_to)
        date_param = f'{start:%Y%m%d}-{end:%Y%m%d}' if start != end else f'{start:%Y%m%d}'

        # O parâmetro competition pode ser um rótulo do catálogo, por exemplo
        # "🏆 Copa do Brasil". A filtragem é feita pelo slug da ESPN e também
        # pelo nome retornado, evitando que uma competição válida seja perdida.
        selected = [competition] if competition else None

        for league in ESPN_CALENDAR_LEAGUES:
            try:
                data = self._fetch_scoreboard(league, date_param)
            except Exception:
                # Uma liga indisponível não pode impedir as demais.
                continue

            for x in data.get('events', []):
                event_id = str(x.get('id') or '')
                if not event_id or event_id in seen:
                    continue

                c = (x.get('competitions') or [{}])[0]
                league_obj = c.get('league') or {}
                raw_comp = (
                    league_obj.get('name')
                    or league_obj.get('abbreviation')
                    or ((x.get('season') or {}).get('displayName'))
                    or ''
                )
                comp = self._canonical_competition(league, raw_comp)

                if not self._selected_competition_matches(league, raw_comp, selected):
                    continue

                teams = c.get('competitors') or []
                home = next(
                    (t for t in teams if t.get('homeAway') == 'home'),
                    teams[0] if teams else {},
                )
                away = next(
                    (t for t in teams if t.get('homeAway') == 'away'),
                    teams[1] if len(teams) > 1 else {},
                )
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
                    'competition_raw': raw_comp,
                    'competition_slug': league,
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
