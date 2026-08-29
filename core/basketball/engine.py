from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class BasketballSourceError(RuntimeError):
    """Erro de cobertura, fonte ou reconstrução de dados de basquete."""


@dataclass(frozen=True)
class BasketballSource:
    competition: str
    country: str
    module: str
    metrics: tuple[str, ...]

    def __getattr__(self, name: str):
        from importlib import import_module
        return getattr(import_module(self.module), name)


_SOURCES = {
    "NBA": BasketballSource(
        "NBA", "USA", "core.basketball.nba",
        ("points", "field_goals", "three_pointers", "free_throws", "rebounds", "assists", "steals", "blocks", "turnovers", "quarters", "halves", "player_minutes"),
    ),
    "NBB": BasketballSource(
        "NBB", "Brasil", "core.basketball.nbb",
        ("points", "field_goals", "three_pointers", "free_throws", "rebounds", "assists", "steals", "blocks", "turnovers", "efficiency", "shooting", "quarters", "player_stats"),
    ),
}


def supported_competitions() -> list[str]:
    return list(_SOURCES)


def get_source(competition: str) -> BasketballSource:
    key = str(competition or "").strip().upper()
    if key not in _SOURCES:
        raise BasketballSourceError(f"Competição de basquete não suportada: {competition}")
    return _SOURCES[key]


def collect_team_history(competition: str, team: str, months: int = 8) -> dict[str, Any]:
    """Interface comum: devolve histórico bruto/normalizado da competição."""
    source = get_source(competition)
    return source.collect_team_history(team, months)


def collect_player_stats(competition: str, team: str, months: int = 8) -> Any:
    source = get_source(competition)
    return source.collect_player_stats(team, months)


def collect_game(competition: str, game_id: str) -> dict[str, Any]:
    source = get_source(competition)
    return source.collect_game(game_id)
