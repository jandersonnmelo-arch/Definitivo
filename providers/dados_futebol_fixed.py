from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .dados_futebol import DadosFutebolProvider, _find_match_records
from core.persistent_api_cache import get_json_persistent

MANAUS = ZoneInfo('America/Manaus')


class DadosFutebolProviderFixed(DadosFutebolProvider):
    """Adaptador final da Série B com cache persistente e limite de 10 chamadas/minuto."""

    name = 'Dados Futebol'

    def _cache_ttl(self, path):
        # O campeonato muda raramente; partidas e estatísticas podem ser atualizadas.
        if path == '/campeonatos':
            return 7 * 24 * 3600
        if path.endswith('/partidas'):
            return 15 * 60
        if '/estatisticas' in path:
            return 30 * 60
        if '/escalacao' in path or '/escalação' in path:
            return 6 * 3600
        return 30 * 60

    def _get(self, path):
        if not self.token:
            raise RuntimeError('chave [api_futebol] não configurada')
        return get_json_persistent(
            url='https://api.dadosfutebol.com.br/v1' + path,
            path=path,
            provider=self.name,
            token=self.token,
            ttl_seconds=self._cache_ttl(path),
        )

    def matches(self, date_from, date_to, competition=None):
        # Consulta uma borda de ±1 dia e aplica o filtro final no fuso oficial do app.
        start = datetime.fromisoformat(date_from) - timedelta(days=1)
        end = datetime.fromisoformat(date_to) + timedelta(days=1)
        rows = super().matches(start.date().isoformat(), end.date().isoformat(), competition)
        wanted_start = datetime.fromisoformat(date_from).date()
        wanted_end = datetime.fromisoformat(date_to).date()
        out = []
        for row in rows:
            try:
                local_date = datetime.fromisoformat(str(row.get('start_time')).replace('Z', '+00:00')).astimezone(MANAUS).date()
            except Exception:
                continue
            if wanted_start <= local_date <= wanted_end:
                out.append(row)
        return out

    def match_details(self, match_id):
        metadata = match_id if isinstance(match_id, dict) else {}
        mid = str(metadata.get('provider_match_id') or metadata.get('id') or match_id)
        if mid.startswith('df:'):
            mid = mid[3:]

        detail = self._get(f'/partidas/{mid}/estatisticas')
        try:
            lineup = self._get(f'/partidas/{mid}/escalacao')
        except Exception:
            # Compatibilidade com instalações que expõem o caminho acentuado.
            try:
                lineup = self._get(f'/partidas/{mid}/escalação')
            except Exception:
                lineup = {}

        match_stub = {
            'home_id': metadata.get('home_id'),
            'away_id': metadata.get('away_id'),
            'home_name': metadata.get('home_name', ''),
            'away_name': metadata.get('away_name', ''),
        }

        for item, home, away, dt, _ in _find_match_records(detail):
            match_stub['home_id'] = home['id'] or match_stub['home_id']
            match_stub['away_id'] = away['id'] or match_stub['away_id']
            match_stub['home_name'] = home['name'] or match_stub['home_name']
            match_stub['away_name'] = away['name'] or match_stub['away_name']
            break

        players = self._players_from_lineup(lineup, match_stub)
        stats = self._team_stats(detail, match_stub)
        player_stats = self._player_stats(detail, players)

        return {'stats': stats, 'players': players, 'player_stats': player_stats}
