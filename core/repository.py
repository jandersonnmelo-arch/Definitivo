"""Compatibility facade for the canonical database repository.

The database-first implementation lives in core.db. Older modules may still
import core.repository, so this facade re-exports the canonical functions
without maintaining a second persistence implementation.
"""
from core.db import (
    canonical_id,
    canonical_player_id,
    canonical_team_id,
    connect,
    init_db,
    record_api_usage,
    usage_today,
    calls_last_minute,
    upsert_match,
    get_provider_id,
    upsert_match_stats,
    upsert_players,
    upsert_player_stats,
    add_diagnostic,
    get_matches,
    get_match,
    get_stats,
    get_players,
    get_diagnostics,
    team_history,
    metric_history,
)

__all__ = [
    'canonical_id', 'canonical_player_id', 'canonical_team_id', 'connect',
    'init_db', 'record_api_usage', 'usage_today', 'calls_last_minute',
    'upsert_match', 'get_provider_id', 'upsert_match_stats', 'upsert_players',
    'upsert_player_stats', 'add_diagnostic', 'get_matches', 'get_match',
    'get_stats', 'get_players', 'get_diagnostics', 'team_history',
    'metric_history'
]
