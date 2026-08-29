"""Módulo de basquete do Premium Football Analytics.

As fontes e métricas de cada competição permanecem isoladas; o dispatcher
oferece uma interface comum para o restante do aplicativo.
"""

from .engine import BasketballSourceError, get_source, supported_competitions

__all__ = ["BasketballSourceError", "get_source", "supported_competitions"]
