from datetime import datetime,timezone
from .base import FootballProvider
from core.http_cache import get_json
from core.normalizer import normalize_status,normalize_metric

BASE='https://site.api.espn.com/apis/site/v2/sports/soccer'

class ESPNProvider(FootballProvider):
    name='ESPN'
    def __init__(self,league='all'):self.league=league
    def available(self):return True
    def matches(self,date_from,date_to,competition=None):
        out=[]; start=datetime.fromisoformat(date_from); end=datetime.fromisoformat(date_to)
        cur=start
        while cur<=end:
            ds=cur.strftime('%Y%m%d'); data=get_json(f'{BASE}/{self.league}/scoreboard',{'dates':ds},provider='ESPN')
            for x in data.get('events',[]):
                comp=((x.get('competitions') or [{}])[0].get('league') or {}).get('name') or ((x.get('season') or {}).get('displayName'))
                if competition and competition.lower() not in str(comp).lower():continue
                c=(x.get('competitions') or [{}])[0]; teams=c.get('competitors') or []
                home=next((t for t in teams if t.get('homeAway')=='home'),teams[0] if teams else {})
                away=next((t for t in teams if t.get('homeAway')=='away'),teams[1] if len(teams)>1 else {})
                st=x.get('status',{});typ=st.get('type',{})
                out.append({'id':str(x.get('id')),'provider_match_id':str(x.get('id')),'sport':'Futebol','competition':comp,'season':str((x.get('season') or {}).get('year') or ''),'start_time':x.get('date'),'status':normalize_status(typ.get('name') or typ.get('state')),'minute':None,'home_id':(home.get('team') or {}).get('id'),'home_name':(home.get('team') or {}).get('displayName') or home.get('displayName',''),'home_short':(home.get('team') or {}).get('abbreviation'),'away_id':(away.get('team') or {}).get('id'),'away_name':(away.get('team') or {}).get('displayName') or away.get('displayName',''),'away_short':(away.get('team') or {}).get('abbreviation'),'home_score':self._score(home),'away_score':self._score(away),'source':self.name})
            cur=cur.fromordinal(cur.toordinal()+1)
        return out
    @staticmethod
    def _score(t):
        try:return int(t.get('score')) if t.get('score') is not None else None
        except Exception:return None
    def match_details(self,match_id):
        data=get_json(f'{BASE}/{self.league}/summary',{'event':match_id},provider='ESPN');stats=[];players=[]
        box=data.get('boxscore') or {}
        for team_block in box.get('teams') or []:
            tid=(team_block.get('team') or {}).get('id')
            for s in team_block.get('statistics') or []:
                metric=normalize_metric(s.get('name') or s.get('displayName'));val=s.get('displayValue',s.get('value'))
                if isinstance(val,str) and val.endswith('%'):val=val[:-1]
                try:val=float(val) if val is not None else None
                except Exception:val=None
                if val is not None:stats.append({'team_id':tid,'metric':metric,'value':val,'source':self.name})
        for team_block in box.get('players') or []:
            tid=(team_block.get('team') or {}).get('id')
            for group in team_block.get('statistics') or []:
                labels=group.get('labels') or group.get('names') or []
                for p in group.get('athletes') or group.get('players') or []:
                    ath=p.get('athlete') or {};pid=ath.get('id')
                    if not pid:continue
                    players.append({'id':int(pid),'team_id':tid,'name':ath.get('displayName') or ath.get('fullName') or 'Sem nome','position':(ath.get('position') or {}).get('abbreviation') if isinstance(ath.get('position'),dict) else ath.get('position')})
                    vals=p.get('statistics') or []
                    for i,val in enumerate(vals):
                        if i>=len(labels) or val in (None,'--','-'):continue
                        try:num=float(str(val).replace('%',''))
                        except Exception:continue
                        players.append({'id':int(pid),'team_id':tid,'name':ath.get('displayName') or ath.get('fullName') or 'Sem nome','position':None,'_stat':{'metric':normalize_metric(labels[i]),'value':num}})
        player_stats=[];clean_players=[]
        seen=set()
        for p in players:
            if '_stat' in p:player_stats.append({'player_id':p['id'],'metric':p['_stat']['metric'],'value':p['_stat']['value'],'source':self.name})
            else:
                key=(p['id'],p['team_id'])
                if key not in seen:clean_players.append(p);seen.add(key)
        return {'stats':stats,'players':clean_players,'player_stats':player_stats}
