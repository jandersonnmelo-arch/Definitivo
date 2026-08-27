import os,requests
from .base import FootballProvider
from core.normalizer import normalize_status,normalize_metric
BASE='https://api.football-data.org/v4'

def _secret():
    for n in ('CHAVE_FD','FOOTBALL_DATA_TOKEN','FOOTBALL_DATA_API_KEY'):
        v=os.getenv(n)
        if v:return v
    try:
        import streamlit as st
        for n in ('CHAVE_FD','FOOTBALL_DATA_TOKEN','FOOTBALL_DATA_API_KEY'):
            try:
                v=st.secrets.get(n)
                if v:return v
            except Exception:pass
    except Exception:pass
    return None

class FootballDataProvider(FootballProvider):
    name='Football-Data.org'
    def __init__(self):self.key=_secret()
    def available(self):return bool(self.key)
    def _get(self,path,params=None):
        if not self.key:raise RuntimeError('CHAVE_FD não configurada')
        r=requests.get(BASE+path,headers={'X-Auth-Token':self.key},params=params or {},timeout=20)
        if r.status_code==429:raise RuntimeError('rate limit (429)')
        r.raise_for_status();return r.json()
    def matches(self,date_from,date_to,competition=None):
        p={'dateFrom':date_from,'dateTo':date_to}
        if competition:p['competitions']=competition
        data=self._get('/matches',p);out=[]
        for x in data.get('matches',[]):
            mid=x['id'];out.append({'id':mid,'provider_match_id':mid,'sport':'Futebol','competition':x.get('competition',{}).get('name'),'season':str(x.get('season',{}).get('startDate','')[:4]),'start_time':x.get('utcDate'),'status':normalize_status(x.get('status')),'minute':x.get('minute'),'home_id':x.get('homeTeam',{}).get('id'),'home_name':x.get('homeTeam',{}).get('name',''),'home_short':x.get('homeTeam',{}).get('tla'),'away_id':x.get('awayTeam',{}).get('id'),'away_name':x.get('awayTeam',{}).get('name',''),'away_short':x.get('awayTeam',{}).get('tla'),'home_score':x.get('score',{}).get('fullTime',{}).get('home'),'away_score':x.get('score',{}).get('fullTime',{}).get('away'),'source':self.name})
        return out
    def match_details(self,match_id):
        x=self._get(f'/matches/{match_id}').get('match',{});stats=[]
        for side in ('homeTeam','awayTeam'):
            team=x.get(side,{})
            for key,val in (team.get('statistics') or {}).items():
                v=val.get('value') if isinstance(val,dict) else val
                if v is not None:stats.append({'team_id':team.get('id'),'metric':normalize_metric(key),'value':v,'source':self.name})
        return {'stats':stats,'players':[],'player_stats':[]}
