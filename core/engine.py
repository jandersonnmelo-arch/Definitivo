from math import exp,factorial
from core.db import connect
from core.normalizer import METRICS,average,source_rank

def poisson(k,lam):
    if lam is None or lam<0:return 0.0
    return exp(-lam)*lam**k/factorial(k)

def outcome_probabilities(home_xg,away_xg):
    if home_xg is None or away_xg is None:return {'home':None,'draw':None,'away':None}
    h=d=a=0.0
    for x in range(10):
        for y in range(10):
            p=poisson(x,home_xg)*poisson(y,away_xg)
            if x>y:h+=p
            elif x==y:d+=p
            else:a+=p
    s=h+d+a
    return {'home':round(h/s*100,1),'draw':round(d/s*100,1),'away':round(a/s*100,1)} if s else {'home':None,'draw':None,'away':None}

def _team_values(team_id,metric,before,limit=10):
    """Uma fonte por métrica/jogo. Nunca tira média de duas fontes diferentes para o mesmo evento."""
    c=connect();rows=c.execute('''SELECT m.id,m.start_time,s.value,s.source FROM match_stats s JOIN matches m ON m.id=s.match_id
      WHERE s.team_id=? AND s.metric=? AND m.status='FINISHED' AND m.start_time < ? ORDER BY m.start_time DESC''',(team_id,metric,before)).fetchall();c.close()
    by_match={}
    for r in rows:
        item=dict(r);mid=item['id'];old=by_match.get(mid)
        if old is None or source_rank(item.get('source'))<source_rank(old.get('source')):by_match[mid]=item
    selected=sorted(by_match.values(),key=lambda x:x.get('start_time') or '',reverse=True)[:limit]
    return [r['value'] for r in selected]

def _goals(team_id,before,limit=10):
    c=connect();rows=c.execute('''SELECT id,home_id,away_id,home_score,away_score FROM matches WHERE sport='Futebol' AND status='FINISHED'
      AND start_time < ? AND (home_id=? OR away_id=?) ORDER BY start_time DESC LIMIT ?''',(before,team_id,team_id,limit)).fetchall();c.close()
    scored=[];conceded=[]
    for r in rows:
        if r['home_id']==team_id:scored.append(r['home_score']);conceded.append(r['away_score'])
        else:scored.append(r['away_score']);conceded.append(r['home_score'])
    return average(scored),average(conceded),len(rows)

def team_profile(team_id,before,limit=10):
    scored,conceded,n=_goals(team_id,before,limit);out={'sample':n,'goals_for':scored,'goals_against':conceded}
    for key in METRICS:
        if key=='goals':continue
        vals=_team_values(team_id,key,before,limit);out[key]=average(vals);out[key+'_sample']=len(vals)
    # Se a fonte fornece xG histórico, ele passa a ser a base preferencial do modelo.
    out['xg']=out.get('expected_goals');out['xg_sample']=out.get('expected_goals_sample',0)
    return out

def build_pre_match_analysis(match,limit=10):
    before=match.get('start_time') or ''
    h=team_profile(match['home_id'],before,limit) if match.get('home_id') else {'sample':0}
    a=team_profile(match['away_id'],before,limit) if match.get('away_id') else {'sample':0}
    # Preferência: xG histórico real. Fallback transparente: gols marcados/sofridos.
    h_attack=h.get('xg') if h.get('xg_sample',0)>0 else h.get('goals_for')
    a_attack=a.get('xg') if a.get('xg_sample',0)>0 else a.get('goals_for')
    h_def=a.get('xg') if a.get('xg_sample',0)>0 else a.get('goals_against')
    a_def=h.get('xg') if h.get('xg_sample',0)>0 else h.get('goals_against')
    hxg=average([h_attack,h_def]);axg=average([a_attack,a_def]);p=outcome_probabilities(hxg,axg)
    coverage={}
    for key,label in METRICS.items():coverage[key]={'home':h.get(key+'_sample',0),'away':a.get(key+'_sample',0)}
    return {'home':h,'away':a,'xg_home':hxg,'xg_away':axg,'probabilities':p,'coverage':coverage,'sample_home':h.get('sample',0),'sample_away':a.get('sample',0)}
