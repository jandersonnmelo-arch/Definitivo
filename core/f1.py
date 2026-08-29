import math
import time
from datetime import datetime, timezone
import pandas as pd
import requests
import streamlit as st
BASE='https://api.jolpi.ca/ergast/f1'; SEASON='2026'; CACHE_TTL=3600
SESSION=requests.Session(); SESSION.headers.update({'User-Agent':'PremiumMultiSportAnalytics/1.0','Accept':'application/json'})
def clean(v): return ' '.join(str(v or '').split()).strip()
def api_get(path,params=None):
    last=None
    for i in range(3):
        try:
            r=SESSION.get(f'{BASE}/{path.lstrip("/")}',params=params or {},timeout=(10,30)); r.raise_for_status(); return r.json()
        except (requests.Timeout,requests.ConnectionError,requests.HTTPError) as e:
            last=e
            if i<2: time.sleep(i+1)
    raise last or RuntimeError('Falha na API Jolpica F1.')
def races(p): return p.get('MRData',{}).get('RaceTable',{}).get('Races',[])
def race_datetime(r):
    try: return datetime.fromisoformat(f'{r.get("date")}T{r.get("time") or "00:00:00Z"}'.replace('Z','+00:00'))
    except (ValueError,TypeError): return None
def completed(rs):
    now=datetime.now(timezone.utc); return sorted([r for r in rs if race_datetime(r) and race_datetime(r)<now],key=race_datetime)
def future(rs):
    now=datetime.now(timezone.utc); return sorted([r for r in rs if race_datetime(r) and race_datetime(r)>=now],key=race_datetime)
def recent(rs,n=5): return completed(rs)[-n:]
def driver_name(d): return clean(f'{d.get("givenName","")} {d.get("familyName","")}')
def pos(v):
    try:return int(str(v))
    except:return 99
def driver_key(r): return r.get('Driver',{}).get('driverId')
def constructor_name(r): return clean(r.get('Constructor',{}).get('name'))
@st.cache_data(ttl=CACHE_TTL,show_spinner=False)
def season_races(): return api_get(f'{SEASON}/races.json',{'limit':100})
@st.cache_data(ttl=CACHE_TTL,show_spinner=False)
def driver_standings(): return api_get(f'{SEASON}/driverstandings.json',{'limit':100})
@st.cache_data(ttl=CACHE_TTL,show_spinner=False)
def constructor_standings(): return api_get(f'{SEASON}/constructorstandings.json',{'limit':100})
@st.cache_data(ttl=CACHE_TTL,show_spinner=False)
def race_results(n): return api_get(f'{SEASON}/{n}/results.json',{'limit':100})
@st.cache_data(ttl=CACHE_TTL,show_spinner=False)
def qualifying_results(n): return api_get(f'{SEASON}/{n}/qualifying.json',{'limit':100})
@st.cache_data(ttl=CACHE_TTL,show_spinner=False)
def pitstop_results(n): return api_get(f'{SEASON}/{n}/pitstops.json',{'limit':100})
def result_rows(n):
    rs=races(race_results(n)); return (rs[0].get('Results',[]),rs[0] if rs else None)
def standings():
    dl=driver_standings().get('MRData',{}).get('StandingsTable',{}).get('StandingsLists',[]); cl=constructor_standings().get('MRData',{}).get('StandingsTable',{}).get('StandingsLists',[]); d={}; c={}
    if dl:
        for x in dl[0].get('DriverStandings',[]):
            a=x.get('Driver',{}); co=(x.get('Constructors') or [{}])[0]; k=a.get('driverId')
            if k:d[k]={'name':driver_name(a),'code':clean(a.get('code')),'points':float(x.get('points') or 0),'wins':int(x.get('wins') or 0),'position':pos(x.get('position')),'constructor_id':co.get('constructorId'),'constructor':clean(co.get('name'))}
    if cl:
        for x in cl[0].get('ConstructorStandings',[]):
            a=x.get('Constructor',{}); k=a.get('constructorId')
            if k:c[k]={'name':clean(a.get('name')),'points':float(x.get('points') or 0),'wins':int(x.get('wins') or 0),'position':pos(x.get('position'))}
    return d,c
def recent_driver_stats(rs,n=5):
    out={}; selected=recent(rs,n)
    for idx,r in enumerate(selected):
        rows,_=result_rows(r['round']); w=.70+.30*((idx+1)/max(1,len(selected)))
        for row in rows:
            did=driver_key(row)
            if not did:continue
            p=pos(row.get('position')); fast=pos(row.get('FastestLap',{}).get('rank'))==1; x=out.setdefault(did,{'score':0.,'weight':0.,'finishes':[],'fastest':0}); fs=max(0.,(21-min(p,20))/20.)
            if p>=99:fs*=.35
            x['score']+=(fs+(.05 if fast else 0))*w; x['weight']+=w; x['finishes'].append(p if p<99 else None); x['fastest']+=int(fast)
    for x in out.values():
        x['score']=x['score']/x['weight'] if x['weight'] else .25; v=[z for z in x['finishes'] if z is not None]; x['avg_finish']=sum(v)/len(v) if v else 99.
    return out
def prediction(rs):
    d,c=standings(); f=recent_driver_stats(rs,5); rows=[]; mx=max([x['points'] for x in d.values()] or [1]); mt=max([x['points'] for x in c.values()] or [1])
    for k,x in d.items():
        z=f.get(k,{'score':.25,'avg_finish':15.,'fastest':0}); t=c.get(x['constructor_id'],{'points':0}); score=.60*z['score']+.25*x['points']/mx+.15*t['points']/mt
        rows.append({'id':k,'Piloto':x['name'],'Equipe':x['constructor'],'Score':score,'Pontos':x['points'],'Vitórias':x['wins'],'Média chegada (5)':z['avg_finish'],'Voltas rápidas (5)':z['fastest']})
    rows.sort(key=lambda x:x['Score'],reverse=True); ss=[math.exp(5*x['Score']) for x in rows]; total=sum(ss) or 1
    for i,(x,s) in enumerate(zip(rows,ss)): x['Vitória %']=100*s/total; x['Top 3/Pódio %']=min(99.5,100/(1+i*.38)); x['Pontos esperados']={1:25,2:18,3:15,4:12,5:10}.get(i+1,0)*(0.65+.35*x['Top 3/Pódio %']/100)
    return rows
