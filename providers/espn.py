from datetime import datetime
from .base import FootballProvider
from core.http_cache import get_json
from core.normalizer import normalize_status,normalize_metric

BASE='https://site.api.espn.com/apis/site/v2/sports/soccer'
CDN='https://cdn.espn.com/core/soccer/game'

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

    @classmethod
    def _extract_players(cls, box):
        players=[]; player_stats=[]; seen=set()
        for team_block in box.get('players') or []:
            if not isinstance(team_block,dict): continue
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
                    if not isinstance(ath,dict): continue
                    pid=ath.get('id') or p.get('id') or p.get('playerId')
                    if not pid: continue
                    try: pid=int(pid)
                    except Exception: continue
                    name=ath.get('displayName') or ath.get('fullName') or ath.get('shortName') or p.get('displayName') or 'Sem nome'
                    pos=ath.get('position') or p.get('position')
                    if isinstance(pos,dict): pos=pos.get('abbreviation') or pos.get('displayName')
                    key=(pid,tid)
                    if key not in seen:
                        players.append({'id':pid,'team_id':tid,'team_name':tname,'name':name,'position':pos,'source':'ESPN'});seen.add(key)
                    vals=p.get('statistics')
                    if vals is None: vals=p.get('stats')
                    if isinstance(vals,dict): vals=list(vals.values())
                    if not isinstance(vals,list): continue
                    for i,val in enumerate(vals):
                        if i>=len(labels) or val in (None,'--','-'): continue
                        n=cls._num(val)
                        if n is None: continue
                        label=labels[i]
                        if isinstance(label,dict): label=label.get('name') or label.get('displayName') or label.get('key')
                        player_stats.append({'player_id':pid,'metric':normalize_metric(label),'value':n,'source':'ESPN'})
        return players,player_stats

    @classmethod
    def _extract_players_recursive(cls, node, team_id=None, team_name=None, depth=0):
        """Fallback for ESPN payloads whose player data is outside boxscore.players."""
        players=[]; stats=[]; seen=set(); stat_seen=set()
        if node is None or depth>10: return players,stats
        if isinstance(node,list):
            for item in node:
                p,s=cls._extract_players_recursive(item,team_id,team_name,depth+1)
                for x in p:
                    if x['id'] not in seen: players.append(x);seen.add(x['id'])
                stats.extend(s)
            return players,stats
        if not isinstance(node,dict): return players,stats
        local_team=node.get('team') if isinstance(node.get('team'),dict) else {}
        tid=node.get('teamId') or local_team.get('id') or team_id
        tname=node.get('teamName') or local_team.get('displayName') or local_team.get('name') or team_name
        ath=node.get('athlete') or node.get('player')
        if isinstance(ath,dict):
            pid=ath.get('id') or node.get('id') or node.get('playerId')
            name=ath.get('displayName') or ath.get('fullName') or ath.get('shortName') or node.get('displayName') or node.get('fullName')
            if pid and name:
                try: pid=int(pid)
                except Exception: pid=None
                if pid:
                    pos=ath.get('position') or node.get('position')
                    if isinstance(pos,dict): pos=pos.get('abbreviation') or pos.get('displayName')
                    players.append({'id':pid,'team_id':tid,'team_name':tname,'name':name,'position':pos,'source':'ESPN'})
                    labels=node.get('labels') or node.get('names') or []
                    vals=node.get('statistics') or node.get('stats') or []
                    if isinstance(vals,dict): vals=list(vals.values())
                    if isinstance(vals,list) and isinstance(labels,list):
                        for i,val in enumerate(vals):
                            if i>=len(labels) or val in (None,'--','-'): continue
                            n=cls._num(val)
                            if n is None: continue
                            label=labels[i]
                            if isinstance(label,dict): label=label.get('name') or label.get('displayName') or label.get('key')
                            stats.append({'player_id':pid,'metric':normalize_metric(label),'value':n,'source':'ESPN'})
        # Direct athlete/player objects can also occur under roster/starter/substitute keys.
        for key,value in node.items():
            if key in {'plays','leaders','notes','odds'}: continue
            if isinstance(value,(dict,list)):
                p,s=cls._extract_players_recursive(value,tid,tname,depth+1)
                for x in p:
                    if x['id'] not in seen: players.append(x);seen.add(x['id'])
                stats.extend(s)
        # De-duplicate stats.
        clean=[]
        for s in stats:
            k=(s.get('player_id'),s.get('metric'),s.get('value'))
            if k not in stat_seen: stat_seen.add(k);clean.append(s)
        return players,clean

    def match_details(self,match_id):
        data=get_json(f'{BASE}/{self.league}/summary',{'event':match_id},provider='ESPN')
        stats=[]; players=[]; player_stats=[]
        box=data.get('boxscore') or {}
        for team_block in box.get('teams') or []:
            if not isinstance(team_block,dict): continue
            tid=(team_block.get('team') or {}).get('id')
            tname=(team_block.get('team') or {}).get('displayName') or (team_block.get('team') or {}).get('name')
            for s in team_block.get('statistics') or []:
                if not isinstance(s,dict): continue
                metric=normalize_metric(s.get('name') or s.get('displayName'))
                val=self._num(s.get('displayValue',s.get('value')))
                if val is not None: stats.append({'team_id':tid,'team_name':tname,'metric':metric,'value':val,'source':self.name})

        players,player_stats=self._extract_players(box)

        if not players:
            try:
                pkg=get_json(CDN,{'xhr':'1','gameId':match_id},provider='ESPN')
                game=pkg.get('gamepackageJSON') if isinstance(pkg,dict) else None
                if isinstance(game,dict):
                    alt_box=game.get('boxscore') or {}
                    alt_players,alt_stats=self._extract_players(alt_box)
                    if alt_players:
                        players=alt_players;player_stats=alt_stats
                    else:
                        alt_players,alt_stats=self._extract_players_recursive(game)
                        if alt_players: players=alt_players;player_stats=alt_stats
            except Exception:
                pass

        # Last fallback: inspect the summary payload itself for roster/athlete structures.
        if not players:
            try:
                fb_players,fb_stats=self._extract_players_recursive(data)
                if fb_players:
                    players=fb_players;player_stats=fb_stats
            except Exception:
                pass

        return {'stats':stats,'players':players,'player_stats':player_stats}
