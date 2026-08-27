from datetime import datetime
from zoneinfo import ZoneInfo

MANAUS = ZoneInfo("America/Manaus")

METRICS = {
    "goals":"Gols", "shots":"Finalizações", "shots_on_target":"Finalizações no alvo",
    "corners":"Escanteios", "passes_completed":"Passes certos", "possession":"Posse (%)",
    "fouls":"Faltas", "offsides":"Impedimentos", "yellow_cards":"Cartões amarelos",
    "red_cards":"Cartões vermelhos", "saves":"Defesas do goleiro", "woodwork":"Bola na trave",
    "goal_kicks":"Tiros de meta"
}


def clean_number(value):
    if value is None: return None
    if isinstance(value,(int,float)): return float(value)
    s=str(value).strip().replace('%','').replace(',','.')
    try: return float(s)
    except ValueError: return None


def manaos_time(iso):
    if not iso: return "—"
    try:
        dt=datetime.fromisoformat(iso.replace('Z','+00:00')).astimezone(MANAUS)
        return dt.strftime('%d/%m %H:%M')
    except Exception: return iso


def normalize_status(status):
    s=(status or '').upper()
    if s in {'LIVE','IN_PLAY','1H','2H','ET','P','LIVE'}: return 'LIVE'
    if s in {'PAUSED','HT'}: return 'PAUSED'
    if s in {'FINISHED','FT','AET','PEN'}: return 'FINISHED'
    if s in {'POSTPONED','SUSPENDED','CANCELLED'}: return s
    return 'SCHEDULED'


def normalize_metric(name):
    s=(name or '').lower().strip().replace(' ','_').replace('-','_')
    aliases={
      'total_shots':'shots','shots_total':'shots','shots_on_goal':'shots_on_target',
      'shots_on_target':'shots_on_target','corner_kicks':'corners','accurate_passes':'passes_completed',
      'yellowcards':'yellow_cards','redcards':'red_cards','goalkeeper_saves':'saves','offsides':'offsides'
    }
    return aliases.get(s,s)


def average(values):
    vals=[clean_number(v) for v in values]; vals=[v for v in vals if v is not None]
    return round(sum(vals)/len(vals),2) if vals else None
