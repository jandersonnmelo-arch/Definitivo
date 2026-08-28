import html
import re
import unicodedata

from .base import FootballProvider
from core.http_cache import get_html
from core.normalizer import normalize_match_metric

BASE = 'https://tribuna.com/en/match/'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}


class TribunaProvider(FootballProvider):
    """Fonte complementar para estatísticas de equipe ausentes.

    É usada somente como fallback. A fonte não substitui estatísticas já
    persistidas por Dados Futebol, ESPN, FotMob ou API-Football.
    """

    name = 'Tribuna'

    def available(self):
        return True

    def matches(self, date_from, date_to, competition=None):
        return []

    @staticmethod
    def _norm_name(value):
        s = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().lower()
        s = re.sub(r'\b(fc|cf|sc|ec|ac|club|clube|football|futbol|calcio|real)\b', ' ', s)
        return re.sub(r'[^a-z0-9]+', ' ', s).strip()

    @classmethod
    def _slug(cls, value):
        return cls._norm_name(value).replace(' ', '-')

    @classmethod
    def _candidate_urls(cls, match):
        home = cls._slug(match.get('home_name'))
        away = cls._slug(match.get('away_name'))
        if not home or not away:
            return []
        return [
            f'{BASE}{away}-vs-{home}/',
            f'{BASE}{home}-vs-{away}/',
        ]

    @staticmethod
    def _text(html_text):
        text = re.sub(r'<script\b[^>]*>.*?</script>', ' ', html_text, flags=re.I | re.S)
        text = re.sub(r'<style\b[^>]*>.*?</style>', ' ', text, flags=re.I | re.S)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = html.unescape(text)
        return re.sub(r'\s+', ' ', text).strip()

    @staticmethod
    def _pair(text, label):
        """Extrai os dois valores de uma estatística no bloco de Match stats."""
        label_re = re.escape(label)
        patterns = [
            rf'(\d+(?:\.\d+)?)\s*{label_re}\s*(\d+(?:\.\d+)?)',
            rf'{label_re}\s*(\d+(?:\.\d+)?)\s*(?:\||/)\s*(\d+(?:\.\d+)?)',
            rf'{label_re}\s*(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)',
        ]
        for pattern in patterns:
            m = re.search(pattern, text, flags=re.I)
            if m:
                return float(m.group(1)), float(m.group(2))
        return None

    @staticmethod
    def _stats_window(text):
        lower = text.lower()
        start = lower.find('match stats')
        if start < 0:
            start = lower.find('match statistics')
        if start < 0:
            return text
        end_candidates = [
            lower.find('starting 11', start + 10),
            lower.find('starting lineup', start + 10),
            lower.find('lineups', start + 10),
        ]
        ends = [x for x in end_candidates if x >= 0]
        end = min(ends) if ends else min(len(text), start + 12000)
        return text[start:end]

    def match_details(self, match):
        last_error = None
        for url in self._candidate_urls(match):
            try:
                raw, final_url = get_html(url, HEADERS)
                text = self._stats_window(self._text(raw))
                stats = []

                for label, metric in (
                    ('Throw-ins', 'player_throws'),
                    ('Throw ins', 'player_throws'),
                    ('Goal kicks', 'goal_kicks'),
                ):
                    pair = self._pair(text, label)
                    if pair is None:
                        continue
                    home_value, away_value = pair
                    stats.extend([
                        {
                            'team_id': match.get('home_id'),
                            'team_name': match.get('home_name'),
                            'metric': normalize_match_metric(metric),
                            'value': home_value,
                            'source': self.name,
                        },
                        {
                            'team_id': match.get('away_id'),
                            'team_name': match.get('away_name'),
                            'metric': normalize_match_metric(metric),
                            'value': away_value,
                            'source': self.name,
                        },
                    ])
                    # Evita duplicar Throw-ins se a página usar as duas grafias.
                    if metric == 'player_throws':
                        break

                if stats:
                    return {'stats': stats, 'players': [], 'player_stats': []}
                last_error = RuntimeError(f'Tribuna: estatísticas ausentes em {final_url or url}')
            except Exception as exc:
                last_error = exc

        raise last_error or RuntimeError('Tribuna: partida não localizada')
