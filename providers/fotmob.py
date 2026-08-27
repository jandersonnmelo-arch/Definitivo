import json,re,html
from .base import FootballProvider
from core.http_cache import get_json,get_html
from core.normalizer import normalize_metric
SEARCH='https://apigw.fotmob.com/searchapi/suggest';PAGE='https://www.fotmob.com/match/'
class FotMobProvider(FootballProvider):
    name='FotMob'
    def available(self):return True
    def matches(self,date_from,date_to,competition=None):return []
    def _find_match_id(self,match):
        data=get_json(SEARCH,{'term':f"{match.get('home_name','')} {match.get('away_name','')}",'lang':'en'},provider='FotMob');target_date=str(match.get('start_time') or '')[:10]
        for group in data.get('matchSuggest',[]) or []:
            for opt in group.get('options',[]) or []:
                p=opt.get('payload') or {};hn=str(p.get('homeName','')).lower();an=str(p.get('awayName','')).lower();md=str(p.get('matchDate',''))[:10]
                if p.get('id') and str(match.get('home_name','')).lower() in hn and str(match.get('away_name','')).lower() in an and (not target_date or not md or md==target_date):return str(p['id'])
        return None
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
    def match_details(self,match):
        fid=self._find_match_id(match)
        if not fid:raise RuntimeError('partida não localizada por nome/data')
        text,_=get_html(PAGE+fid);data=self._next_data(text);pp=((data.get('props') or {}).get('pageProps') or {});general=pp.get('general') or {};content=pp.get('content') or {};home=general.get('homeTeam') or {};away=general.get('awayTeam') or {};home_id=home.get('id');away_id=away.get('id');home_name=home.get('name');away_name=away.get('name');stats=[]
        all_stats=(((content.get('stats') or {}).get('Periods') or {}).get('All') or {}).get('stats') or []
        for group in all_stats:
            for item in group.get('stats') or []:
                vals=item.get('stats') or []
                if not isinstance(vals,list) or len(vals)<2:continue
                metric=normalize_metric(item.get('key') or item.get('title'))
                for tid,tname,val in ((home_id,home_name,vals[0]),(away_id,away_name,vals[1])):
                    n=self._num(val)
                    if n is not None:stats.append({'team_id':tid,'team_name':tname,'metric':metric,'value':n,'source':self.name})
        players=[];player_stats=[]
        for pid,p in (content.get('playerStats') or {}).items():
            if not isinstance(p,dict) or not p.get('stats'):continue
            try:player_id=int(p.get('id') or pid)
            except Exception:continue
            team_id=p.get('teamId');team_name=p.get('teamName');players.append({'id':player_id,'team_id':team_id,'team_name':team_name,'name':p.get('name') or 'Sem nome','position':p.get('usualPosition')})
            for group in p.get('stats') or []:
                gstats=group.get('stats') if isinstance(group,dict) else None
                if not isinstance(gstats,dict):continue
                for label,item in gstats.items():
                    obj=item.get('stat') if isinstance(item,dict) else item;val=obj.get('value',obj.get('total')) if isinstance(obj,dict) else obj;n=self._num(val)
                    if n is not None:player_stats.append({'player_id':player_id,'metric':normalize_metric(item.get('key') if isinstance(item,dict) else label),'value':n,'source':self.name})
        return {'stats':stats,'players':players,'player_stats':player_stats}
