from __future__ import annotations
from datetime import date, timedelta
from zoneinfo import ZoneInfo
import time
import requests
import pandas as pd

BASE='https://site.api.espn.com/apis/site/v2/sports/football/nfl'
SEASON=2026
MANAUS=ZoneInfo('America/Manaus')
S=requests.Session(); S.headers.update({'User-Agent':'PremiumMultiSportAnalytics/1.0','Accept':'application/json'})

NFL_TEAMS={
'Atlanta Falcons':'ATL','Arizona Cardinals':'ARI','Baltimore Ravens':'BAL','Buffalo Bills':'BUF','Carolina Panthers':'CAR','Chicago Bears':'CHI','Cincinnati Bengals':'CIN','Cleveland Browns':'CLE','Dallas Cowboys':'DAL','Denver Broncos':'DEN','Detroit Lions':'DET','Green Bay Packers':'GB','Houston Texans':'HOU','Indianapolis Colts':'IND','Jacksonville Jaguars':'JAX','Kansas City Chiefs':'KC','Las Vegas Raiders':'LV','Los Angeles Chargers':'LAC','Los Angeles Rams':'LAR','Miami Dolphins':'MIA','Minnesota Vikings':'MIN','New England Patriots':'NE','New Orleans Saints':'NO','New York Giants':'NYG','New York Jets':'NYJ','Philadelphia Eagles':'PHI','Pittsburgh Steelers':'PIT','San Francisco 49ers':'SF','Seattle Seahawks':'SEA','Tampa Bay Buccaneers':'TB','Tennessee Titans':'TEN','Washington Commanders':'WSH'
}

def api_get(path='',params=None):
    last=None
    for attempt in range(3):
        try:
            r=S.get(f'{BASE}/{path.lstrip("/")}',params=params or {},timeout=(10,30)); r.raise_for_status(); return r.json()
        except (requests.RequestException,ValueError) as e:
            last=e
            if attempt<2: time.sleep(attempt+1)
    raise RuntimeError(f'Falha na fonte NFL/ESPN: {last}')

def _manaus(v):
    dt=pd.to_datetime(v,utc=True,errors='coerce')
    return None if pd.isna(dt) else dt.tz_convert(MANAUS)

def scoreboard(start:date,end:date):
    if end<start:return []
    # ESPN aceita intervalos de datas no scoreboard; usamos blocos de até 7 dias para reduzir carga.
    rows=[]; cur=start
    while cur<=end:
        chunk_end=min(end,cur+timedelta(days=6))
        data=api_get('scoreboard',{'dates':f'{cur:%Y%m%d}-{chunk_end:%Y%m%d}','limit':100})
        rows.extend(data.get('events',[])); cur=chunk_end+timedelta(days=1)
    unique={str(x.get('id')):x for x in rows if x.get('id')}
    return list(unique.values())

def team_code_from_event(event):
    for comp in event.get('competitions',[]):
        for c in comp.get('competitors',[]):
            abbr=(c.get('team') or {}).get('abbreviation') or ''
            if abbr:return str(abbr).upper()
    return ''

def team_schedule(team_code,start:date,end:date):
    events=scoreboard(start,end); out=[]
    for e in events:
        comp=(e.get('competitions') or [{}])[0]; competitors=comp.get('competitors') or []
        if not any(str((c.get('team') or {}).get('abbreviation','')).upper()==team_code.upper() for c in competitors):continue
        dt=_manaus(e.get('date')); home=away=None; hs=as_=None
        for c in competitors:
            t=(c.get('team') or {}).get('displayName') or (c.get('team') or {}).get('name') or '—'; score=c.get('score')
            if c.get('homeAway')=='home':home=t; hs=score
            else:away=t; as_=score
        status=((comp.get('status') or {}).get('type') or {}).get('description') or ((comp.get('status') or {}).get('type') or {}).get('name') or 'Scheduled'
        out.append({'game_id':e.get('id'),'Data':dt.strftime('%d/%m/%Y') if dt else '—','Hora (Manaus)':dt.strftime('%H:%M') if dt else '—','Casa':home,'Fora':away,'Placar':f'{hs} x {as_}' if hs is not None and as_ is not None else '—','Status':status})
    return sorted(out,key=lambda x:(x['Data'],x['Hora (Manaus)']))

def summary(event_id):
    return api_get('summary',{'event':event_id})

def _stat_value(stats,name):
    for s in stats or []:
        if str(s.get('name','')).lower()==name.lower():
            return s.get('value') or s.get('displayValue')
    return None

def parse_team_stats(summary_json):
    rows=[]
    for box in summary_json.get('boxscore',{}).get('teams',[]) or []:
        team=(box.get('team') or {}).get('displayName') or '—'; stats=box.get('statistics') or []
        rows.append({'Equipe':team,'Pontos':_stat_value(stats,'points'),'Total Yards':_stat_value(stats,'totalYards'),'Passing Yards':_stat_value(stats,'netPassingYards') or _stat_value(stats,'passingYards'),'Rushing Yards':_stat_value(stats,'rushingYards'),'Turnovers':_stat_value(stats,'turnovers'),'First Downs':_stat_value(stats,'firstDowns'),'Third Down %':_stat_value(stats,'thirdDownEfficiency'),'Red Zone %':_stat_value(stats,'redZoneEfficiency'),'Penalidades':_stat_value(stats,'totalPenaltiesYards')})
    return rows

def parse_players(summary_json):
    rows=[]
    for group in summary_json.get('boxscore',{}).get('players',[]) or []:
        team=(group.get('team') or {}).get('displayName') or '—'
        for stat_group in group.get('statistics',[]) or []:
            labels=stat_group.get('labels') or []
            for athlete in stat_group.get('athletes',[]) or []:
                a=athlete.get('athlete') or {}; stats=athlete.get('stats') or []
                row={'Equipe':team,'Jogador':a.get('displayName') or a.get('fullName') or '—','Posição':a.get('position',{}).get('abbreviation') if isinstance(a.get('position'),dict) else a.get('position')}
                row.update({str(labels[i]):stats[i] for i in range(min(len(labels),len(stats)))})
                rows.append(row)
    return rows

def recent_team_games(team_code,n=5):
    end=date.today(); start=end-timedelta(days=180)
    rows=team_schedule(team_code,start,end)
    done=[r for r in rows if r['Placar']!='—']
    return done[-n:]

def team_averages(team_code,n=5):
    games=recent_team_games(team_code,n); agg=[]
    for g in games:
        try: agg.append(parse_team_stats(summary(g['game_id'])))
        except Exception: continue
    flat={}
    for game in agg:
        for row in game:
            if team_code.upper() in str(row['Equipe']).upper() or True:
                for k,v in row.items():
                    if k=='Equipe':continue
                    try: flat.setdefault(k,[]).append(float(str(v).replace('%','').split('-')[0]))
                    except Exception: pass
    return games,{k:sum(v)/len(v) for k,v in flat.items() if v}
