import json, re, html, unicodedata
from .base import FootballProvider
from core.http_cache import get_json, get_html
from core.normalizer import normalize_match_metric, normalize_player_metric

SEARCH = 'https://www.fotmob.com/api/data/search/suggest'
PAGE = 'https://www.fotmob.com/match/'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}


class FotMobProvider(FootballProvider):
    name = 'FotMob'

    def available(self):
        return True

    def matches(self, date_from, date_to, competition=None):
        return []

    @staticmethod
    def _norm_name(value):
        s = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().lower()
        s = re.sub(r'\b(fc|cf|sc|ec|ac|club|football|futbol|calcio)\b', ' ', s)
        return re.sub(r'[^a-z0-9]+', ' ', s).strip()

    @staticmethod
    def _date_match(payload, target_date):
        if not isinstance(payload, dict):
            return False
        raw = str(payload.get('matchDate') or payload.get('utcTime') or payload.get('date') or payload.get('startTime') or '')
        return not target_date or target_date in raw or raw[:10] == target_date

    def _find_match_id(self, match):
        home = self._norm_name(match.get('home_name'))
        away = self._norm_name(match.get('away_name'))
        target_date = str(match.get('start_time') or '')[:10]
        terms = [f"{match.get('home_name', '')} {match.get('away_name', '')}", f"{match.get('away_name', '')} {match.get('home_name', '')}", str(match.get('home_name', ''))]
        candidates, seen = [], set()
        for term in terms:
            data = get_json(SEARCH, {'term': term, 'hits': 50, 'lang': 'en'}, HEADERS, provider='FotMob')
            groups = data.get('matchSuggest') or data.get('matches') or [] if isinstance(data, dict) else []
            if isinstance(groups, dict):
                groups = groups.get('options', [])
            if not isinstance(groups, list):
                continue
            for group in groups:
                options = group.get('options', []) if isinstance(group, dict) else []
                if not options and isinstance(group, dict) and group.get('id'):
                    options = [group]
                if not isinstance(options, list):
                    continue
                for opt in options:
                    if not isinstance(opt, dict):
                        continue
                    p = opt.get('payload') or opt
                    if not isinstance(p, dict):
                        continue
                    fid = p.get('id') or p.get('matchId')
                    if not fid or str(fid) in seen:
                        continue
                    seen.add(str(fid))
                    hn = self._norm_name(p.get('homeName') or p.get('homeTeamName'))
                    an = self._norm_name(p.get('awayName') or p.get('awayTeamName'))
                    if not _same_names(home, hn) or not _same_names(away, an):
                        continue
                    if not self._date_match(p, target_date):
                        continue
                    candidates.append((8 + (1 if p.get('leagueName') else 0), str(fid)))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    @staticmethod
    def _next_data(text):
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', text, re.S)
        if not m:
            raise RuntimeError('FotMob: __NEXT_DATA__ não encontrado')
        return json.loads(html.unescape(m.group(1)))

    @staticmethod
    def _num(v):
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v.replace('%', '').replace(',', '.'))
            except Exception:
                return None
        return None

    @staticmethod
    def _stat_value(obj):
        if isinstance(obj, dict):
            inner = obj.get('stat') if isinstance(obj.get('stat'), dict) else obj
            for k in ('value', 'total', 'number'):
                if isinstance(inner, dict) and k in inner:
                    n = FotMobProvider._num(inner.get(k))
                    if n is not None:
                        return n
            return None
        return FotMobProvider._num(obj)

    @staticmethod
    def _player_from_obj(obj, team_id=None, team_name=None):
        if not isinstance(obj, dict):
            return None
        p = obj.get('player') or obj.get('athlete') or obj
        if not isinstance(p, dict):
            return None
        pid = p.get('id') or obj.get('id')
        if not pid:
            return None
        try:
            pid = int(pid)
        except Exception:
            return None
        tid = p.get('teamId') or obj.get('teamId') or team_id
        tname = p.get('teamName') or obj.get('teamName') or team_name
        name = p.get('name') or p.get('fullName') or p.get('displayName') or obj.get('name') or obj.get('fullName') or obj.get('displayName')
        if not name:
            return None
        position = p.get('usualPosition') or p.get('position') or obj.get('usualPosition') or obj.get('position')
        if isinstance(position, dict):
            position = position.get('displayName') or position.get('abbreviation')
        return {'id': pid, 'team_id': tid, 'team_name': tname, 'name': name, 'position': position}

    @classmethod
    def _extract_lineup_players(cls, lineup, default_team_id=None, default_team_name=None):
        out, seen = [], set()
        def add(obj, tid=None, tname=None):
            p = cls._player_from_obj(obj, tid, tname)
            if p and p['id'] not in seen:
                seen.add(p['id']); out.append(p)
        def walk(node, tid=None, tname=None, depth=0):
            if node is None or depth > 10:return
            if isinstance(node, list):
                for item in node: walk(item, tid, tname, depth + 1)
                return
            if not isinstance(node, dict):return
            local_tid = node.get('teamId') or node.get('team_id') or tid
            local_tname = node.get('teamName') or node.get('team_name') or tname
            if node.get('player') or node.get('athlete') or (node.get('id') and (node.get('name') or node.get('fullName') or node.get('displayName'))):add(node, local_tid, local_tname)
            for key, value in node.items():
                if key in {'formation', 'coach', 'events'}:continue
                if isinstance(value, (dict, list)):walk(value, local_tid, local_tname, depth + 1)
        walk(lineup, default_team_id, default_team_name)
        return out

    @classmethod
    def _extract_player_stats(cls, raw, default_team_id=None, default_team_name=None):
        players, player_stats, seen = [], [], set()
        def visit(node, tid=None, tname=None, depth=0):
            if node is None or depth > 10:return
            if isinstance(node, list):
                for item in node: visit(item, tid, tname, depth + 1)
                return
            if not isinstance(node, dict):return
            local_tid = node.get('teamId') or node.get('team_id') or tid
            local_tname = node.get('teamName') or node.get('team_name') or tname
            p = cls._player_from_obj(node, local_tid, local_tname)
            if p:
                pid = p['id']
                if pid not in seen:players.append(p); seen.add(pid)
                groups = node.get('stats') or node.get('statistics') or []
                if isinstance(groups, dict):groups = list(groups.values())
                if isinstance(groups, list):
                    for group in groups:
                        if not isinstance(group, dict):continue
                        gstats = group.get('stats') if isinstance(group.get('stats'), dict) else group
                        if isinstance(gstats, dict):
                            for label, item in gstats.items():
                                if label in {'player','athlete','stats','statistics'}:continue
                                key = item.get('key') if isinstance(item, dict) else label
                                n = cls._stat_value(item)
                                if n is not None:player_stats.append({'player_id': pid, 'metric': normalize_player_metric(key or label), 'value': n, 'source': cls.name})
            for key, value in node.items():
                if key in {'formation', 'coach', 'events'}:continue
                if isinstance(value, (dict, list)):visit(value, local_tid, local_tname, depth + 1)
        visit(raw, default_team_id, default_team_name)
        return players, player_stats

    def match_details(self, match):
        fid = self._find_match_id(match)
        if not fid:raise RuntimeError('FotMob: partida não localizada por equipes/data')
        text, _ = get_html(PAGE + fid, HEADERS);data = self._next_data(text);pp = ((data.get('props') or {}).get('pageProps') or {});general = pp.get('general') or {};content = pp.get('content') or {}
        if not isinstance(general, dict) or not isinstance(content, dict) or not content:raise RuntimeError('FotMob: página encontrada, mas sem dados detalhados pré-renderizados')
        home = general.get('homeTeam') or {};away = general.get('awayTeam') or {};home_id, away_id = home.get('id'), away.get('id');home_name, away_name = home.get('name'), away.get('name');stats=[]
        all_stats = (((content.get('stats') or {}).get('Periods') or {}).get('All') or {}).get('stats') or []
        if isinstance(all_stats, list):
            for group in all_stats:
                if not isinstance(group, dict):continue
                for item in group.get('stats') or []:
                    if not isinstance(item, dict):continue
                    vals=item.get('stats')
                    if not isinstance(vals,list) or len(vals)<2:continue
                    metric=normalize_match_metric(item.get('key') or item.get('title'))
                    for tid,tname,val in ((home_id,home_name,vals[0]),(away_id,away_name,vals[1])):
                        n=self._num(val)
                        if n is not None:stats.append({'team_id':tid,'team_name':tname,'metric':metric,'value':n,'source':self.name})
        raw_players=content.get('playerStats');players,player_stats=self._extract_player_stats(raw_players,None,None)
        if not players:
            lineup=content.get('lineup') or content.get('lineups') or content.get('playerLineups') or {};players=self._extract_lineup_players(lineup)
        if not players:
            for key in ('lineup','lineups','playerLineups','playerStats','rosters'):
                if key in content:
                    p2,s2=self._extract_player_stats(content.get(key),None,None)
                    if p2:players.extend(p2);player_stats.extend(s2)
        clean=[];seen=set();valid_team_ids={str(x) for x in (home_id,away_id) if x is not None}
        for p in players:
            if p['id'] in seen:continue
            if p.get('team_id') is not None and valid_team_ids and str(p['team_id']) not in valid_team_ids:continue
            seen.add(p['id']);clean.append(p)
        return {'stats':stats,'players':clean,'player_stats':player_stats}

def _same_names(a,b):return bool(a and b and (a==b or a in b or b in a))
