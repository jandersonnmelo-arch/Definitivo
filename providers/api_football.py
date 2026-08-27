import os,re
from .base import FootballProvider
from core.http_cache import get_json
from core.db import usage_today,calls_last_minute
from core.normalizer import normalize_metric
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
    def __init__(self):self.key=_secret()
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
                self._fixture_teams[x.get('fixture',{}).get('id')]={ 'home':(t.get('home') or {}).get('name'),'away':(t.get('away') or {}).get('name') }
                return x.get('fixture',{}).get('id')
        return None
    def match_details(self,match_id):
        data=self._get('/fixtures/statistics',{'fixture':match_id});stats=[];names=getattr(self,'_fixture_teams',{}).get(match_id,{})
        for b in data:
            tid=(b.get('team') or {}).get('id');tname=(b.get('team') or {}).get('name')
            for item in b.get('statistics') or []:
                metric=normalize_metric(item.get('type'));val=item.get('value')
                if isinstance(val,str) and val.endswith('%'):val=val[:-1]
                try:val=float(val) if val is not None else None
                except Exception:val=None
                if val is not None:stats.append({'team_id':tid,'team_name':tname,'metric':metric,'value':val,'source':self.name})
        return {'stats':stats,'players':[],'player_stats':[]}
