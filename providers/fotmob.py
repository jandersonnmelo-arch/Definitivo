import json,re,html,unicodedata
from .base import FootballProvider
from core.http_cache import get_json,get_html
from core.normalizer import normalize_metric
SEARCH='https://apigw.fotmob.com/searchapi/suggest';PAGE='https://www.fotmob.com/match/'
class FotMobProvider(FootballProvider):
    name='FotMob'
    def available(self):return True
    def matches(self,date_from,date_to,competition=None):return []
    @staticmethod
    def _norm_name(value):
        s=unicodedata.normalize('NFKD',str(value or '')).encode('ascii','ignore').decode().lower()
        s=re.sub(r'\b(fc|cf|sc|ec|ac|club|football|futbol|calcio)\b',' ',s)
        return re.sub(r'[^a-z0-9]+',' ',s).strip()
    @staticmethod
    def _date_match(payload,target_date):
        if not target_date:return True
        raw=str(payload.get('matchDate') or payload.get('utcTime') or payload.get('date') or '')
        if target_date in raw:return True
        return raw[:10]==target_date
    def _find_match_id(self,match):
        home=self._norm_name(match.get('home_name'));away=self._norm_name(match.get('away_name'))
        target_date=str(match.get('start_time') or '')[:10]
        terms=[f"{match.get('home_name','')} {match.get('away_name','')}",f"{match.get('away_name','')} {match.get('home_name','')}",str(match.get('home_name',''))]
        candidates=[]
        seen=set()
        for term in terms:
            data=get_json(SEARCH,{'term':term,'lang':'en'},provider='FotMob')
            for group in data.get('matchSuggest',[]) or []:
                for opt in group.get('options',[]) or []:
                    p=opt.get('payload') or {};fid=p.get('id')
                    if not fid or str(fid) in seen:continue
                    seen.add(str(fid));hn=self._norm_name(p.get('homeName'));an=self._norm_name(p.get('awayName'))
                    if not self._date_match(p,target_date):continue
                    score=0
                    if home and (home==hn or home in hn or hn in home):score+=4
                    if away and (away==an or away in an or an in away):score+=4
                    if home and away and home==an and away==hn:score-=8
                    if p.get('leagueName'):score+=1
                    candidates.append((score,str(fid),p))
        if not candidates:return None
        candidates.sort(key=lambda x:x[0],reverse=True)
        best=candidates[0]
        return best[1] if best[0]>=7 else None
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
        if not fid:raise RuntimeError('FotMob: partida não localizada por equipes/data')
        text,_=get_html(PAGE+fid);data=self._next_data(text);pp=((data.get('props') or {}).get('pageProps') or {});general=pp.get('general') or {};content=pp.get('content') or {}
        if not general or not content:
            raise RuntimeError('FotMob: partida encontrada, mas os dados detalhados ainda não estão no HTML pré-renderizado')
        home=general.get('homeTeam') or {};away=general.get('awayTeam') or {};home_id=home.get('id');away_id=away.get('id');home_name=home.get('name');away_name=away.get('name');stats=[]
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
