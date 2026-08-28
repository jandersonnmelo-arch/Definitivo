from datetime import datetime
import re
from .base import FootballProvider
from core.http_cache import get_json
from core.normalizer import normalize_status, normalize_match_metric, canonical_player_metric
from core.db import add_diagnostic

BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
CDN = 'https://cdn.espn.com/core/soccer/game'


class ESPNProvider(FootballProvider):
    name = 'ESPN'
    DEBUG_PLAYER_NAME = 'Vinícius Júnior'

    def __init__(self, league='all'):
        self.league = league

    def available(self): return True

    def matches(self, date_from, date_to, competition=None):
        out=[];cur=datetime.fromisoformat(date_from);end=datetime.fromisoformat(date_to)
        while cur<=end:
            ds=cur.strftime('%Y%m%d');data=get_json(f'{BASE}/{self.league}/scoreboard',{'dates':ds},provider='ESPN')
            for x in data.get('events',[]):
                comp=((x.get('competitions') or [{}])[0].get('league') or {}).get('name') or ((x.get('season') or {}).get('displayName'))
                if competition and competition.lower() not in str(comp).lower():continue
                c=(x.get('competitions') or [{}])[0];teams=c.get('competitors') or []
                home=next((t for t in teams if t.get('homeAway')=='home'),teams[0] if teams else {});away=next((t for t in teams if t.get('homeAway')=='away'),teams[1] if len(teams)>1 else {})
                st=x.get('status') or {};typ=st.get('type') or {};status=normalize_status(typ.get('name') or typ.get('state') or typ.get('description'),typ.get('completed'))
                out.append({'id':str(x.get('id')),'provider_match_id':str(x.get('id')),'sport':'Futebol','competition':comp,'season':str((x.get('season') or {}).get('year') or ''),'start_time':x.get('date'),'status':status,'minute':self._minute(st,status),'home_id':(home.get('team') or {}).get('id'),'home_name':(home.get('team') or {}).get('displayName') or home.get('displayName',''),'home_short':(home.get('team') or {}).get('abbreviation'),'away_id':(away.get('team') or {}).get('id'),'away_name':(away.get('team') or {}).get('displayName') or away.get('displayName',''),'away_short':(away.get('team') or {}).get('abbreviation'),'home_score':self._score(home) if status in ('LIVE','PAUSED','FINISHED') else None,'away_score':self._score(away) if status in ('LIVE','PAUSED','FINISHED') else None,'source':self.name})
            cur=cur.fromordinal(cur.toordinal()+1)
        return out

    @staticmethod
    def _score(t):
        try:return int(t.get('score')) if t.get('score') is not None else None
        except Exception:return None
    @staticmethod
    def _minute(status_obj,status):
        if status not in ('LIVE','PAUSED'):return None
        clock=status_obj.get('displayClock')
        if clock:
            try:return int(float(str(clock).split(':')[0]))
            except Exception:pass
        try:return int(status_obj.get('period')) if status_obj.get('period') is not None else None
        except Exception:return None
    @staticmethod
    def _key(value):
        s=str(value or '').strip();s=re.sub(r'([a-z0-9])([A-Z])',r'\1_\2',s);return re.sub(r'[^A-Za-z0-9]+','_',s).strip('_').lower()
    @classmethod
    def _num(cls,value):
        if isinstance(value,bool):return None
        if isinstance(value,(int,float)):return float(value)
        if isinstance(value,dict):
            for key in ('value','displayValue','numericValue','total'):
                if key in value:
                    n=cls._num(value.get(key))
                    if n is not None:return n
            return None
        if value is None:return None
        s=str(value).strip()
        if not s or s in {'--','-','N/A','null'}:return None
        m=re.fullmatch(r'(\d+(?:\.\d+)?)\s*/\s*\d+(?:\.\d+)?',s)
        if m:return float(m.group(1))
        try:return float(s.replace('%','').replace(',','.'))
        except Exception:pass
        m=re.fullmatch(r'(\d+):(\d{1,2})',s)
        if m:return float(m.group(1))+float(m.group(2))/60.0
        return None
    @classmethod
    def _team_stat_value(cls,stat):
        if not isinstance(stat,dict):return cls._num(stat)
        for key in ('value','numericValue','total'):
            if key in stat:
                n=cls._num(stat.get(key))
                if n is not None:return n
        return cls._num(stat.get('displayValue'))
    @classmethod
    def _player_metric(cls,label):
        key=cls._key(label)
        aliases={'g':'goals','goal':'goals','goals_scored':'goals','total_goals':'goals','a':'assists','assist':'assists','goal_assists':'assists','assists_total':'assists','sog':'shots_on_target','shots_on_goal':'shots_on_target','shots_on_target':'shots_on_target','shots_on_target_total':'shots_on_target','shot':'shots','shots':'shots','total_shots':'shots','shots_total':'shots','ac_pass':'passes_completed','ac_passes':'passes_completed','accurate_pass':'passes_completed','accurate_passes':'passes_completed','accuratepasses':'passes_completed','passes_accurate':'passes_completed','passes_completed':'passes_completed','completed_passes':'passes_completed','passing_completions':'passes_completed','pass_completions':'passes_completed','completions':'passes_completed','tklw':'tackles_won','tkl_w':'tackles_won','tackles_won':'tackles_won','tackleswon':'tackles_won','successful_tackles':'tackles_won','won_tackles':'tackles_won','total_tackles':'tackles','tackles_total':'tackles','tkl':'tackles','tackles':'tackles','effective_tackles':'tackles','fc':'fouls','fouls':'fouls','fouls_committed':'fouls','foulscommitted':'fouls','fa':'was_fouled','fouled':'was_fouled','fouls_suffered':'was_fouled','fouls_suffered_total':'was_fouled','yc':'yellow_cards','yellow_card':'yellow_cards','yellow_cards':'yellow_cards','yellowcards':'yellow_cards','rc':'red_cards','red_card':'red_cards','red_cards':'red_cards','redcards':'red_cards','sv':'saves','saves':'saves','of':'offsides','offsides':'offsides','min':'minutes_played','minutes':'minutes_played','minutes_played':'minutes_played'}
        return canonical_player_metric(aliases.get(key,key)) or aliases.get(key,key)
    @classmethod
    def _stat_pairs(cls,group,athlete):
        group=group if isinstance(group,dict) else {};athlete=athlete if isinstance(athlete,dict) else {}
        keys=group.get('keys') or group.get('labels') or group.get('names') or group.get('descriptions') or athlete.get('keys') or athlete.get('labels') or athlete.get('names') or athlete.get('descriptions') or []
        if isinstance(keys,str):keys=[keys]
        def values_from(obj):
            for field in ('statistics','stats','values','totals'):
                if field in obj and obj.get(field) is not None:return obj.get(field)
            return None
        values=values_from(athlete)
        if values is None:
            nested=athlete.get('athlete') or athlete.get('player')
            if isinstance(nested,dict):
                values=values_from(nested)
                if not keys:keys=nested.get('keys') or nested.get('labels') or nested.get('names') or nested.get('descriptions') or []
        rows=[]
        if isinstance(values,dict):
            for k,v in values.items():
                n=cls._num(v)
                if n is not None:rows.append((k,n))
            return rows
        if not isinstance(values,list):return rows
        for i,value in enumerate(values):
            label=keys[i] if i<len(keys) else None
            if isinstance(value,dict):
                label=value.get('key') or value.get('name') or value.get('label') or value.get('displayName') or value.get('description') or label;raw=value.get('value',value.get('displayValue',value.get('numericValue',value.get('total'))))
            else:raw=value
            n=cls._num(raw)
            if label is not None and n is not None:rows.append((label,n))
        return rows
    @staticmethod
    def _is_debug_player(name):
        n=re.sub(r'[^a-z]','',str(name or '').lower());return n in {'viniciusjunior','viniciusjr','vinicius'}
    @classmethod
    def _debug_player(cls,match_id,ath,group,item,pairs):
        name=ath.get('displayName') or ath.get('fullName') or ath.get('shortName') or item.get('displayName') or ''
        if not cls._is_debug_player(name):return
        def compact(obj):
            if not isinstance(obj,dict):return obj
            keep={}
            for k,v in obj.items():
                if k in {'statistics','stats','values','totals','keys','labels','names','descriptions','athlete','player','id','displayName','fullName','shortName','position','positionGroup'}:keep[k]=v
            return keep
        payload={'match_id':str(match_id),'player_name':name,'player_id':ath.get('id') or item.get('id') or item.get('playerId'),'group':compact(group),'item':compact(item),'athlete':compact(ath),'parsed_pairs':pairs,'mapped':[(label,cls._player_metric(label),value) for label,value in pairs]}
        add_diagnostic('espn_player_debug','OK',f'VINICIUS_DEBUG {payload}',cls.name,str(match_id))
    @classmethod
    def _extract_players(cls,box,match_id=None):
        players=[];player_stats=[];seen_players=set();seen_stats=set()
        for team_block in box.get('players') or []:
            if not isinstance(team_block,dict):continue
            team=team_block.get('team') or {};tid=team.get('id');tname=team.get('displayName') or team.get('name');groups=team_block.get('statistics') or []
            if not isinstance(groups,list):continue
            for group in groups:
                if not isinstance(group,dict):continue
                athletes=group.get('athletes') or group.get('players') or []
                if not isinstance(athletes,list):continue
                for item in athletes:
                    if not isinstance(item,dict):continue
                    ath=item.get('athlete') or item.get('player') or item
                    if not isinstance(ath,dict):continue
                    pid=ath.get('id') or item.get('id') or item.get('playerId')
                    if not pid:continue
                    try:pid=int(pid)
                    except Exception:continue
                    name=ath.get('displayName') or ath.get('fullName') or ath.get('shortName') or item.get('displayName') or 'Sem nome';pos=ath.get('position') or item.get('position')
                    if isinstance(pos,dict):pos=pos.get('abbreviation') or pos.get('displayName')
                    pkey=(pid,str(tid))
                    if pkey not in seen_players:players.append({'id':pid,'team_id':tid,'team_name':tname,'name':name,'position':pos,'source':cls.name});seen_players.add(pkey)
                    pairs=cls._stat_pairs(group,item)
                    if not pairs and ath is not item:pairs=cls._stat_pairs(group,ath)
                    cls._debug_player(match_id,ath,group,item,pairs)
                    for label,value in pairs:
                        metric=cls._player_metric(label)
                        if metric=='__player_presence__':continue
                        skey=(pid,metric,value)
                        if skey not in seen_stats:player_stats.append({'player_id':pid,'metric':metric,'value':value,'source':cls.name});seen_stats.add(skey)
        return players,player_stats
    def match_details(self,match_id):
        data=get_json(f'{BASE}/{self.league}/summary',{'event':match_id},provider='ESPN');stats=[];players=[];player_stats=[];box=data.get('boxscore') or {}
        for team_block in box.get('teams') or []:
            if not isinstance(team_block,dict):continue
            team=team_block.get('team') or {};tid=team.get('id');tname=team.get('displayName') or team.get('name')
            for s in team_block.get('statistics') or []:
                if not isinstance(s,dict):continue
                metric=normalize_match_metric(s.get('name') or s.get('displayName'));val=self._team_stat_value(s)
                if metric and val is not None:stats.append({'team_id':tid,'team_name':tname,'metric':metric,'value':val,'source':self.name})
        players,player_stats=self._extract_players(box,match_id)
        if not players or not player_stats:
            try:
                pkg=get_json(CDN,{'xhr':'1','gameId':match_id},provider='ESPN');game=pkg.get('gamepackageJSON') if isinstance(pkg,dict) else None
                if isinstance(game,dict):
                    alt_box=game.get('boxscore') or {};alt_players,alt_stats=self._extract_players(alt_box,match_id)
                    if not alt_players or not alt_stats:
                        rec_players,rec_stats=self._extract_players_recursive(game);alt_players=alt_players or rec_players;alt_stats=alt_stats or rec_stats
                    if alt_players:players=alt_players
                    if alt_stats:player_stats=alt_stats
            except Exception:pass
        if not players or not player_stats:
            try:
                fb_players,fb_stats=self._extract_players_recursive(data)
                if fb_players:players=fb_players
                if fb_stats:player_stats=fb_stats
            except Exception:pass
        return {'stats':stats,'players':players,'player_stats':player_stats}
