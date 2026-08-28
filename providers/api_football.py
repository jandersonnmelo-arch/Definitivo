import os,re
from .base import FootballProvider
from core.http_cache import get_json
from core.db import usage_today,calls_last_minute
from core.normalizer import normalize_match_metric
BASE='https://v3.football.api-sports.io'
def _secret():
    names=('API_SPORTS_KEY','API_FOOTBALL_KEY','API_FOOTBALL_TOKEN','APISPORTS_KEY')
    for n in names:
        v=os.getenv(n)
        if v:return v
    try:
        import streamlit as st
        for n in names:
            try:
                v=st.secrets.get(n)
                if v:return v
            except Exception:pass
        try:
            block=st.secrets.get('api_futebol')
            if block:
                for k in ('token','key','api_key'):
                    try:v=block.get(k)
                    except Exception:v=None
                    if v:return v
        except Exception:pass
    except Exception:pass
    return None
def _norm(s):return re.sub(r'[^a-z0-9]+',' ',str(s or '').lower()).strip()
class ApiFootballProvider(FootballProvider):
    name='API-Football';DAILY_SOFT_LIMIT=80;MINUTE_SOFT_LIMIT=8
    def __init__(self):self.key=_secret();self._fixture_teams={}
    def available(self):return bool(self.key)
    def _guard(self):
        if not self.key:raise RuntimeError('chave não configurada')
        u=usage_today(self.name)
        if int(u.get('calls',0))>=self.DAILY_SOFT_LIMIT:raise RuntimeError(f'proteção diária ativa ({u.get("calls",0)} chamadas hoje)')
        if calls_last_minute(self.name)>=self.MINUTE_SOFT_LIMIT:raise RuntimeError('proteção por minuto ativa; aguarde antes de novas chamadas')
    def _get(self,path,params=None):self._guard();return get_json(BASE+path,params or {},{'x-apisports-key':self.key},provider=self.name).get('response',[])
    def matches(self,*args,**kwargs):raise RuntimeError('API-Football é somente fonte de enriquecimento operacional.')
    def resolve_match_id(self,match):
        date=str(match.get('start_time') or '')[:10]
        if not date:raise RuntimeError('data da partida ausente')
        candidates=self._get('/fixtures',{'date':date});hn=_norm(match.get('home_name'));an=_norm(match.get('away_name'))
        for x in candidates:
            t=x.get('teams') or {};h=_norm((t.get('home') or {}).get('name'));a=_norm((t.get('away') or {}).get('name'))
            if (hn in h or h in hn) and (an in a or a in an):
                fid=x.get('fixture',{}).get('id');self._fixture_teams[fid]={'home':(t.get('home') or {}).get('name'),'away':(t.get('away') or {}).get('name')};return fid
        return None
    def _parse_player_stats(self,fixture_id):
        players=[];player_stats=[]
        rows=self._get('/fixtures/players',{'fixture':fixture_id})
        for block in rows:
            team=block.get('team') or {};tid=team.get('id');tname=team.get('name')
            for item in block.get('players') or []:
                p=item.get('player') or {};pid=p.get('id')
                if pid is None:continue
                name=p.get('name') or 'Sem nome';stats=item.get('statistics') or {}
                if isinstance(stats,list):stats=stats[0] if stats else {}
                games=stats.get('games') or {};pos=games.get('position') or games.get('pos')
                players.append({'id':pid,'team_id':tid,'team_name':tname,'name':name,'position':pos,'source':self.name})
                def add(metric,value):
                    if isinstance(value,bool) or value is None:return
                    try:value=float(value)
                    except Exception:return
                    player_stats.append({'player_id':pid,'metric':metric,'value':value,'source':self.name})
                add('minutes',games.get('minutes'));add('rating',games.get('rating'))
                shots=stats.get('shots') or {};goals=stats.get('goals') or {};passes=stats.get('passes') or {};tackles=stats.get('tackles') or {};fouls=stats.get('fouls') or {};cards=stats.get('cards') or {}
                add('shots',shots.get('total'));add('shots_on_target',shots.get('on'));add('goals',goals.get('total'));add('assists',goals.get('assists'))
                add('passes_completed',passes.get('total'));add('key_passes',passes.get('key'));add('tackles',tackles.get('total'));add('interceptions',tackles.get('interceptions'))
                add('fouls',fouls.get('committed'));add('was_fouled',fouls.get('drawn'));add('yellow_cards',cards.get('yellow'));add('red_cards',cards.get('red'))
        return players,player_stats
    def _parse_lineups(self,fixture_id):
        players=[];rows=self._get('/fixtures/lineups',{'fixture':fixture_id})
        for block in rows:
            team=block.get('team') or {};tid=team.get('id');tname=team.get('name')
            for section in ('startXI','substitutes'):
                for item in block.get(section) or []:
                    p=item.get('player') or {};pid=p.get('id')
                    if pid is None:continue
                    players.append({'id':pid,'team_id':tid,'team_name':tname,'name':p.get('name') or 'Sem nome','position':p.get('pos'),'source':self.name})
        return players
    def match_details(self,match_id):
        data=self._get('/fixtures/statistics',{'fixture':match_id});stats=[]
        for b in data:
            tid=(b.get('team') or {}).get('id');tname=(b.get('team') or {}).get('name')
            for item in b.get('statistics') or []:
                metric=normalize_match_metric(item.get('type'));val=item.get('value')
                if isinstance(val,str) and val.endswith('%'):val=val[:-1]
                try:val=float(val) if val is not None else None
                except Exception:val=None
                if val is not None:stats.append({'team_id':tid,'team_name':tname,'metric':metric,'value':val,'source':self.name})
        players=[];player_stats=[]
        try:players,player_stats=self._parse_player_stats(match_id)
        except Exception:pass
        if not players:
            try:players=self._parse_lineups(match_id)
            except Exception:pass
        return {'stats':stats,'players':players,'player_stats':player_stats}
