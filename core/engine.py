from math import exp,factorial
from core.db import connect
from core.normalizer import METRICS,average,source_rank

def poisson(k,lam):
    if lam is None or lam<0:return 0.0
    return exp(-lam)*lam**k/factorial(k)

def poisson_over(lam,line):
    if lam is None:return None
    k=int(line)+1
    return round(max(0.0,1-sum(poisson(i,lam) for i in range(k)))*100,1)

def poisson_under(lam,line):
    if lam is None:return None
    k=int(line)
    return round(max(0.0,sum(poisson(i,lam) for i in range(k+1)))*100,1)

def exact_total_goals(lam,max_goals=4):
    if lam is None:return {}
    out={}
    for k in range(max_goals):out[str(k)]=round(poisson(k,lam)*100,1)
    out[f'{max_goals}+']=round(max(0.0,1-sum(poisson(i,lam) for i in range(max_goals)))*100,1)
    return out

def outcome_probabilities(home_xg,away_xg):
    if home_xg is None or away_xg is None:return {'home':None,'draw':None,'away':None}
    h=d=a=0.0
    for x in range(12):
        for y in range(12):
            q=poisson(x,home_xg)*poisson(y,away_xg)
            if x>y:h+=q
            elif x==y:d+=q
            else:a+=q
    s=h+d+a
    return {'home':round(h/s*100,1),'draw':round(d/s*100,1),'away':round(a/s*100,1)} if s else {'home':None,'draw':None,'away':None}

def _team_values(team_id,metric,before,limit=10):
    c=connect();rows=c.execute('''SELECT m.id,m.start_time,s.value,s.source FROM match_stats s JOIN matches m ON m.id=s.match_id
      WHERE s.team_id=? AND s.metric=? AND m.status='FINISHED' AND m.start_time < ? ORDER BY m.start_time DESC''',(team_id,metric,before)).fetchall();c.close();by_match={}
    for r in rows:
        item=dict(r);mid=item['id'];old=by_match.get(mid)
        if old is None or source_rank(item.get('source'))<source_rank(old.get('source')):by_match[mid]=item
    selected=sorted(by_match.values(),key=lambda x:x.get('start_time') or '',reverse=True)[:limit]
    return [r['value'] for r in selected]

def _goals(team_id,before,limit=10):
    c=connect();rows=c.execute('''SELECT id,home_id,away_id,home_score,away_score FROM matches WHERE sport='Futebol' AND status='FINISHED'
      AND start_time < ? AND (home_id=? OR away_id=?) ORDER BY start_time DESC LIMIT ?''',(before,team_id,team_id,limit)).fetchall();c.close();scored=[];conceded=[]
    for r in rows:
        if r['home_id']==team_id:scored.append(r['home_score']);conceded.append(r['away_score'])
        else:scored.append(r['away_score']);conceded.append(r['home_score'])
    return average(scored),average(conceded),len(rows)

def team_profile(team_id,before,limit=10):
    scored,conceded,n=_goals(team_id,before,limit);out={'sample':n,'goals_for':scored,'goals_against':conceded}
    for key in METRICS:
        if key=='goals':continue
        vals=_team_values(team_id,key,before,limit);out[key]=average(vals);out[key+'_sample']=len(vals)
    out['xg']=out.get('expected_goals');out['xg_sample']=out.get('expected_goals_sample',0)
    return out

def _metric_market(home,away,key,lines):
    hv=home.get(key);av=away.get(key)
    if hv is None and av is None:return None
    lam=sum(v for v in (hv,av) if isinstance(v,(int,float)))
    return {'home':hv,'away':av,'total_expected':round(lam,2),'lines':{str(line):poisson_over(lam,line) for line in lines}}

def build_pre_match_analysis(match,limit=10):
    before=match.get('start_time') or '';h=team_profile(match['home_id'],before,limit) if match.get('home_id') else {'sample':0};a=team_profile(match['away_id'],before,limit) if match.get('away_id') else {'sample':0}
    h_attack=h.get('xg') if h.get('xg_sample',0)>0 else h.get('goals_for');a_attack=a.get('xg') if a.get('xg_sample',0)>0 else a.get('goals_for')
    hxg=average([h_attack,a.get('goals_against')]);axg=average([a_attack,h.get('goals_against')]);total_xg=round(sum(x for x in (hxg,axg) if isinstance(x,(int,float))),2) if hxg is not None or axg is not None else None
    p=outcome_probabilities(hxg,axg)
    btts=round((1-poisson(0,hxg))*(1-poisson(0,axg))*100,1) if hxg is not None and axg is not None else None
    markets={
        'gols':{'expected':total_xg,'over':{str(line):poisson_over(total_xg,line) for line in (0.5,1.5,2.5,3.5)} if total_xg is not None else {},'under':{str(line):poisson_under(total_xg,line) for line in (1.5,2.5,3.5)} if total_xg is not None else {},'exact_total':exact_total_goals(total_xg,4)},
        'ambas_marcam':btts,
        'finalizacoes':_metric_market(h,a,'shots',(19.5,23.5,27.5)),
        'finalizacoes_no_alvo':_metric_market(h,a,'shots_on_target',(6.5,8.5,10.5)),
        'escanteios':_metric_market(h,a,'corners',(7.5,8.5,9.5,10.5)),
        'faltas':_metric_market(h,a,'fouls',(19.5,22.5,25.5,28.5)),
        'cartoes_amarelos':_metric_market(h,a,'yellow_cards',(2.5,3.5,4.5,5.5)),
        'impedimentos':_metric_market(h,a,'offsides',(1.5,2.5,3.5,4.5)),
        'defesas':_metric_market(h,a,'saves',(5.5,7.5,9.5)),
    }
    coverage={key:{'home':h.get(key+'_sample',0),'away':a.get(key+'_sample',0)} for key,label in METRICS.items()}
    return {'home':h,'away':a,'xg_home':hxg,'xg_away':axg,'probabilities':p,'coverage':coverage,'sample_home':h.get('sample',0),'sample_away':a.get('sample',0),'markets':markets,'btts':btts}
