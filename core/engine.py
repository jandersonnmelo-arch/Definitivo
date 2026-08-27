from math import exp,factorial
from collections import defaultdict
from .repository import get_match_stats

def poisson(k,lam): return 0 if lam is None else exp(-lam)*lam**k/factorial(k)
def outcome_probabilities(home_xg,away_xg):
    if home_xg is None or away_xg is None:return {'home':None,'draw':None,'away':None}
    h=d=a=0
    for x in range(9):
        for y in range(9):
            p=poisson(x,home_xg)*poisson(y,away_xg)
            if x>y:h+=p
            elif x==y:d+=p
            else:a+=p
    s=h+d+a; return {'home':h/s,'draw':d/s,'away':a/s}
def build_pre_match_analysis(mid):
    return {'status':'READY','sample_home':0,'sample_away':0,'xg_home':None,'xg_away':None,'probabilities':outcome_probabilities(None,None),'note':'Amostra histórica insuficiente. O motor não inventa médias.'}
def build_live_analysis(mid):
    rows=get_match_stats(mid); grouped=defaultdict(dict)
    for r in rows: grouped[r['team_id']][r['metric']]=r['value']
    return {'status':'READY','teams':dict(grouped),'source_count':len(rows)}
