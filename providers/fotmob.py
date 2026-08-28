import json,re,html,unicodedata
from .base import FootballProvider
from core.http_cache import get_json,get_html
from core.normalizer import normalize_metric
SEARCH='https://www.fotmob.com/api/data/search/suggest';PAGE='https://www.fotmob.com/match/'
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36','Accept-Language':'en-US,en;q=0.9'}
class FotMobProvider(FootballProvider):
    name='FotMob'
    def available(self):return True
    def matches(self,date_from,date_to,competition=None):return []
    @staticmethod
    def _norm_name(value):
        s=unicodedata.normalize('NFKD',str(value or '')).encode('ascii','ignore').decode().lower();s=re.sub(r'\b(fc|cf|sc|ec|ac|club|football|futbol|calcio)\b',' ',s);return re.sub(r'[^a-z0-9]+',' ',s).strip()
    @staticmethod
    def _date_match(payload,target_date):
        raw=str(payload.get('matchDate') or payload.get('utcTime') or payload.get('date') or payload.get('startTime') or '')
        return not target_date or target_date in raw or raw[:10]==target_date
    def _find_match_id(self,match):
        home=self._norm_name(match.get('home_name'));away=self._norm_name(match.get('away_name'));target_date=str(match.get('start_time') or '')[:10]
        terms=[f"{match.get('home_name','')} {match.get('away_name','')}",f"{match.get('away_name','')} {match.get('home_name','')}",str(match.get('home_name',''))]
        candidates=[];seen=set()
        for term in terms:
            data=get_json(SEARCH,{'term':term,'hits':50,'lang':'en'},HEADERS,provider='FotMob')
            groups=data.get('matchSuggest') or data.get('matches') or []
            if isinstance(groups,dict):groups=groups.get('options',[])
            for group in groups:
                options=group.get('options',[]) if isinstance(group,dict) else []
                if not options and isinstance(group,dict) and group.get('id'):options=[group]
                for opt in options:
                    p=opt.get('payload') or opt;fid=p.get('id') or p.get('matchId')
                    if not fid or str(fid) in seen:continue
                    seen.add(str(fid));hn=self._norm_name(p.get('homeName') or p.get('homeTeamName'));an=self._norm_name(p.get('awayName') or p.get('awayTeamName'))
                    if not _same_names(home,hn) or not _same_names(away,an):continue
                    if not self._date_match(p,target_date):continue
                    score=8+(1 if p.get('leagueName') else 0);candidates.append((score,str(fid)))
        if not candidates:return None
        candidates.sort(key=lambda x:x[0],reverse=True);return candidates[0][1]
    @staticmethod
    def _next_data(text):
        m=re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',text,re.S)
        if not m:raise RuntimeError('FotMob: __NEXT_DATA__ não encontrado')
        return json.loads(html.unescape(m.group(1)))
    @staticmethod
    def _num(v):
        if isinstance(v,(int,float)):return float(v)
        if isinstance(v,str):
            try:return float(v.replace('%','').replace(',','.'))
            except Exception:return None
        return None
    @staticmethod
    def _stat_value(obj):
        if isinstance(obj,dict):
            inner=obj.get('stat') if isinstance(obj.get('stat'),dict) else obj
            for k in ('value','total','number'):
                if isinstance(inner,dict) and k in inner:
                    n=FotMobProvider._num(inner.get(k))
                    if n is not None:return n
            return None
        return FotMobProvider._num(obj)
    def match_details(self,match):
        fid=self._find_match_id(match)
        if not fid:raise RuntimeError('FotMob: partida não localizada por equipes/data')
        text,_=get_html(PAGE+fid,HEADERS);data=self._next_data(text);pp=((data.get('props') or {}).get('pageProps') or {});general=pp.get('general') or {};content=pp.get('content') or {}
        if not isinstance(general,dict) or not isinstance(content,dict) or not content:raise RuntimeError('FotMob: página encontrada, mas sem dados detalhados pré-renderizados')
        home=general.get('homeTeam') or {};away=general.get('awayTeam') or {};home_id=home.get('id');away_id=away.get('id');home_name=home.get('name');away_name=away.get('name');stats=[]
        all_stats=(((content.get('stats') or {}).get('Periods') or {}).get('All') or {}).get('stats') or []
        if not isinstance(all_stats,list):all_stats=[]
        for group in all_stats:
            if not isinstance(group,dict):continue
            for item in group.get('stats') or []:
                if not isinstance(item,dict):continue
                vals=item.get('stats')
                if not isinstance(vals,list) or len(vals)<2:continue
                metric=normalize_metric(item.get('key') or item.get('title'))
                for tid,tname,val in ((home_id,home_name,vals[0]),(away_id,away_name,vals[1])):
                    n=self._num(val)
                    if n is not None:stats.append({'team_id':tid,'team_name':tname,'metric':metric,'value':n,'source':self.name})
        players=[];player_stats=[]
        raw_players=content.get('playerStats') or {}
        if isinstance(raw_players,dict):raw_players=list(raw_players.values())
        if not isinstance(raw_players,list):raw_players=[]
        for p in raw_players:
            if not isinstance(p,dict) or not p.get('stats'):continue
            try:player_id=int(p.get('id'))
            except Exception:continue
            team_id=p.get('teamId');team_name=p.get('teamName');players.append({'id':player_id,'team_id':team_id,'team_name':team_name,'name':p.get('name') or 'Sem nome','position':p.get('usualPosition')})
            groups=p.get('stats') or []
            if isinstance(groups,dict):groups=list(groups.values())
            for group in groups:
                if not isinstance(group,dict):continue
                gstats=group.get('stats') if isinstance(group.get('stats'),dict) else {}
                for label,item in gstats.items():
                    key=item.get('key') if isinstance(item,dict) else label;n=self._stat_value(item)
                    if n is not None:player_stats.append({'player_id':player_id,'metric':normalize_metric(key or label),'value':n,'source':self.name})
        if not players:
            lineup=content.get('lineup') or {};lineups=lineup.get('lineups') if isinstance(lineup,dict) else []
            if isinstance(lineups,list):
                for team in lineups:
                    if not isinstance(team,dict):continue
                    tid=team.get('teamId');tname=team.get('teamName')
                    for p in team.get('players') or []:
                        if not isinstance(p,dict):continue
                        obj=p.get('player') or p;pid=obj.get('id')
                        if not pid:continue
                        try:pid=int(pid)
                        except Exception:continue
                        players.append({'id':pid,'team_id':tid,'team_name':tname,'name':obj.get('name') or obj.get('fullName') or 'Sem nome','position':obj.get('usualPosition') or obj.get('position')})
        return {'stats':stats,'players':players,'player_stats':player_stats}
def _same_names(a,b):return bool(a and b and (a==b or a in b or b in a))
