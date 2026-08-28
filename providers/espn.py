from datetime import datetime
from .base import FootballProvider
from core.http_cache import get_json
from core.normalizer import normalize_status,normalize_metric

BASE='https://site.api.espn.com/apis/site/v2/sports/soccer'

class ESPNProvider(FootballProvider):
    name='ESPN'
    def __init__(self,league='all'): self.league=league
    def available(self): return True

    def matches(self,date_from,date_to,competition=None):
        out=[]; cur=datetime.fromisoformat(date_from); end=datetime.fromisoformat(date_to)
        while cur<=end:
            ds=cur.strftime('%Y%m%d')
            data=get_json(f'{BASE}/{self.league}/scoreboard',{'dates':ds},provider='ESPN')
            for x in data.get('events',[]):
                comp=((x.get('competitions') or [{}])[0].get('league') or {}).get('name') or ((x.get('season') or {}).get('displayName'))
                if competition and competition.lower() not in str(comp).lower(): continue
                c=(x.get('competitions') or [{}])[0]; teams=c.get('competitors') or []
                home=next((t for t in teams if t.get('homeAway')=='home'),teams[0] if teams else {})
                away=next((t for t in teams if t.get('homeAway')=='away'),teams[1] if len(teams)>1 else {})
                st=x.get('status') or {}; typ=st.get('type') or {}
                status=normalize_status(typ.get('name') or typ.get('state') or typ.get('description'),typ.get('completed'))
                out.append({'id':str(x.get('id')),'provider_match_id':str(x.get('id')),'sport':'Futebol','competition':comp,'season':str((x.get('season') or {}).get('year') or ''),'start_time':x.get('date'),'status':status,'minute':self._minute(st,status),'home_id':(home.get('team') or {}).get('id'),'home_name':(home.get('team') or {}).get('displayName') or home.get('displayName',''),'home_short':(home.get('team') or {}).get('abbreviation'),'away_id':(away.get('team') or {}).get('id'),'away_name':(away.get('team') or {}).get('displayName') or away.get('displayName',''),'away_short':(away.get('team') or {}).get('abbreviation'),'home_score':self._score(home) if status in ('LIVE','PAUSED','FINISHED') else None,'away_score':self._score(away) if status in ('LIVE','PAUSED','FINISHED') else None,'source':self.name})
            cur=cur.fromordinal(cur.toordinal()+1)
        return out

    @staticmethod
    def _score(t):
        try:return int(t.get('score')) if t.get('score') is not None else None
        except Exception:return None
    @staticmethod
    def _minute(status_obj,status):
        if status not in ('LIVE','PAUSED'): return None
        clock=status_obj.get('displayClock')
        if clock:
            try:return int(float(str(clock).split(':')[0]))
            except Exception: pass
        try:return int(status_obj.get('period')) if status_obj.get('period') is not None else None
        except Exception:return None

    @staticmethod
    def _num(v):
        if isinstance(v,(int,float)): return float(v)
        if isinstance(v,str):
            try:return float(v.replace('%','').replace(',','.'))
            except Exception:return None
        return None

    def match_details(self,match_id):
        data=get_json(f'{BASE}/{self.league}/summary',{'event':match_id},provider='ESPN')
        stats=[]; players=[]; player_stats=[]
        box=data.get('boxscore') or {}
        for team_block in box.get('teams') or []:
            tid=(team_block.get('team') or {}).get('id')
            tname=(team_block.get('team') or {}).get('displayName') or (team_block.get('team') or {}).get('name')
            for s in team_block.get('statistics') or []:
                metric=normalize_metric(s.get('name') or s.get('displayName'))
                val=self._num(s.get('displayValue',s.get('value')))
                if val is not None: stats.append({'team_id':tid,'team_name':tname,'metric':metric,'value':val,'source':self.name})

        for team_block in box.get('players') or []:
            team=(team_block.get('team') or {}); tid=team.get('id'); tname=team.get('displayName') or team.get('name')
            groups=team_block.get('statistics') or []
            if not isinstance(groups,list): continue
            for group in groups:
                if not isinstance(group,dict): continue
                labels=group.get('labels') or group.get('names') or group.get('descriptions') or []
                athletes=group.get('athletes') or group.get('players') or []
                if not isinstance(athletes,list): continue
                for p in athletes:
                    if not isinstance(p,dict): continue
                    ath=p.get('athlete') or p.get('player') or {}
                    pid=ath.get('id') or p.get('id')
                    if not pid: continue
                    try: pid=int(pid)
                    except Exception: continue
                    name=ath.get('displayName') or ath.get('fullName') or ath.get('shortName') or 'Sem nome'
                    pos=ath.get('position')
                    if isinstance(pos,dict): pos=pos.get('abbreviation') or pos.get('displayName')
                    key=(pid,tid)
                    if not any(z.get('_key')==key for z in players):
                        players.append({'id':pid,'team_id':tid,'team_name':tname,'name':name,'position':pos,'source':self.name,'_key':key})
                    vals=p.get('statistics')
                    if vals is None: vals=p.get('stats')
                    if isinstance(vals,dict): vals=list(vals.values())
                    if not isinstance(vals,list): continue
                    for i,val in enumerate(vals):
                        if i>=len(labels) or val in (None,'--','-'): continue
                        n=self._num(val)
                        if n is None: continue
                        label=labels[i]
                        if isinstance(label,dict): label=label.get('name') or label.get('displayName') or label.get('key')
                        player_stats.append({'player_id':pid,'metric':normalize_metric(label),'value':n,'source':self.name})
        for p in players: p.pop('_key',None)
        return {'stats':stats,'players':players,'player_stats':player_stats}
