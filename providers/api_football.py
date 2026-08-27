import os,requests
from .base import FootballProvider
from core.normalizer import normalize_status,normalize_metric
BASE='https://v3.football.api-sports.io'

def _key():
    for n in ('API_FOOTBALL_KEY','API_FOOTBALL_TOKEN','APISPORTS_KEY'):
        v=os.getenv(n)
        if v:return v
    try:
        import streamlit as st
        for n in ('API_FOOTBALL_KEY','API_FOOTBALL_TOKEN','APISPORTS_KEY'):
            try:
                v=st.secrets.get(n)
                if v:return v
            except Exception:pass
    except Exception:pass
    return None

class ApiFootballProvider(FootballProvider):
    name='API-Football'
    def __init__(self):self.key=_key()
    def available(self):return bool(self.key)
    def _get(self,path,params=None):
        if not self.key:raise RuntimeError('API_FOOTBALL_KEY não configurada')
        r=requests.get(BASE+path,headers={'x-apisports-key':self.key},params=params or {},timeout=20)
        if r.status_code==429:raise RuntimeError('rate limit (429)')
        r.raise_for_status(); d=r.json()
        if d.get('errors'):raise RuntimeError(str(d['errors']))
        return d.get('response',[])
    def matches(self,date_from,date_to,competition=None):
        p={'from':date_from,'to':date_to}
        if competition:p['league']=competition
        out=[]
        for x in self._get('/fixtures',p):
            f=x.get('fixture',{});t=x.get('teams',{});g=x.get('goals',{});s=f.get('status',{})
            out.append({'id':f.get('id'),'provider_match_id':f.get('id'),'sport':'Futebol','competition':(x.get('league') or {}).get('name'),'season':str((x.get('league') or {}).get('season') or ''),'start_time':f.get('date'),'status':normalize_status(s.get('short')),'minute':s.get('elapsed'),'home_id':(t.get('home') or {}).get('id'),'home_name':(t.get('home') or {}).get('name',''),'home_short':(t.get('home') or {}).get('code'),'away_id':(t.get('away') or {}).get('id'),'away_name':(t.get('away') or {}).get('name',''),'away_short':(t.get('away') or {}).get('code'),'home_score':g.get('home'),'away_score':g.get('away'),'source':self.name})
        return out
    def match_details(self,match_id):
        stats=[]
        for b in self._get('/fixtures/statistics',{'fixture':match_id}):
            tid=(b.get('team') or {}).get('id')
            for item in b.get('statistics') or []:
                metric=normalize_metric(item.get('type')); val=item.get('value')
                if isinstance(val,str) and val.endswith('%'):val=val[:-1]
                try:val=float(val) if val is not None else None
                except Exception:val=None
                if val is not None:stats.append({'team_id':tid,'metric':metric,'value':val,'source':self.name})
        players=[]; player_stats=[]
        try:
            for b in self._get('/fixtures/players',{'fixture':match_id}):
                team_id=(b.get('team') or {}).get('id')
                for p in b.get('players') or []:
                    pl=p.get('player') or {}; pid=pl.get('id')
                    if not pid:continue
                    players.append({'id':pid,'team_id':team_id,'name':pl.get('name') or 'Sem nome','position':(p.get('statistics') or [{}])[0].get('games',{}).get('position')})
                    for st in p.get('statistics') or []:
                        games=st.get('games') or {}; shots=st.get('shots') or {}; goals=st.get('goals') or {}; passes=st.get('passes') or {}; fouls=st.get('fouls') or {}; cards=st.get('cards') or {}
                        vals={'minutes':games.get('minutes'),'starts':games.get('substitute') is False,'rating':games.get('rating'),'shots':shots.get('total'),'shots_on_target':shots.get('on'),'goals':goals.get('total'),'assists':goals.get('assists'),'passes_completed':passes.get('accuracy'),'fouls':fouls.get('committed'),'yellow_cards':cards.get('yellow'),'red_cards':cards.get('red')}
                        for metric,val in vals.items():
                            if isinstance(val,bool):val=int(val)
                            if val is not None:
                                try:val=float(val)
                                except Exception:continue
                                player_stats.append({'player_id':pid,'metric':normalize_metric(metric),'value':val,'source':self.name})
        except Exception: pass
        return {'stats':stats,'players':players,'player_stats':player_stats}
