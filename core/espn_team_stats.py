import re
from core.http_cache import get_json
from core.normalizer import normalize_match_metric

CDN = 'https://cdn.espn.com/core/soccer/game'


def _num(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for k in ('value','numericValue','total','displayValue'):
            if k in value:
                n = _num(value.get(k))
                if n is not None:
                    return n
        return None
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in {'--','-','N/A','null'}:
        return None
    try:
        return float(s.replace('%','').replace(',','.'))
    except Exception:
        pass
    m = re.match(r'^\s*(\d+(?:\.\d+)?)\s*/\s*\d+(?:\.\d+)?', s)
    return float(m.group(1)) if m else None


def _stat_value(stat):
    if not isinstance(stat, dict):
        return _num(stat)
    for k in ('value','numericValue','total'):
        if k in stat:
            n = _num(stat.get(k))
            if n is not None:
                return n
    return _num(stat.get('displayValue'))


def _team_rows(box):
    out = []
    for block in (box or {}).get('teams') or []:
        if not isinstance(block, dict):
            continue
        team = block.get('team') or {}
        tid = team.get('id') or block.get('teamId')
        tname = team.get('displayName') or team.get('name') or block.get('teamName')
        for stat in block.get('statistics') or []:
            if not isinstance(stat, dict):
                continue
            label = stat.get('name') or stat.get('displayName') or stat.get('label') or stat.get('description')
            metric = normalize_match_metric(label)
            value = _stat_value(stat)
            if tid is not None and metric and value is not None:
                out.append({'team_id': tid, 'team_name': tname, 'metric': metric, 'value': value, 'source': 'ESPN'})
    return out


def fetch_team_stats(event_id):
    """Read team statistics from ESPN's full CDN game package.

    The summary boxscore can omit some soccer indicators. The CDN package
    often contains the same team boxscore with the missing fields populated.
    """
    data = get_json(CDN, {'xhr':'1','gameId':str(event_id)}, provider='ESPN')
    game = data.get('gamepackageJSON') if isinstance(data, dict) else None
    if not isinstance(game, dict):
        return []
    return _team_rows(game.get('boxscore') or {})
