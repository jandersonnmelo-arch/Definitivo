"""Compatibilidade para o módulo FotMob.

O provider oficial fica em providers.fotmob. Este módulo mantém um ponto
canônico em core para integrações antigas que importem core.fotmob.
"""

from providers.fotmob import FotMobProvider

__all__ = ["FotMobProvider"]
