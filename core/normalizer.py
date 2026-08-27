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

STATUS_LABELS = {
    "SCHEDULED": "AGENDADO",
    "LIVE": "EM ANDAMENTO",
    "PAUSED": "INTERVALO",
    "FINISHED": "FINALIZADO",
    "POSTPONED": "ADIADO",
    "SUSPENDED": "SUSPENSO",
    "CANCELLED": "CANCELADO"
}

DIAGNOSTIC_STATUS_LABELS = {"OK":"OK", "ERROR":"ERRO", "WARNING":"AVISO"}


def status_label(status):
    return STATUS_LABELS.get(str(status or "").upper(), str(status or "—"))


def diagnostic_status_label(status):
    return DIAGNOSTIC_STATUS_LABELS.get(str(status or "").upper(), str(status or "—"))


def clean_number(value):
    if value is None: return None
    if isinstance(value,(int,float)): return float(value)
    s=str(value).strip().replace('%','').replace(',','.')
    try: return float(s)
    except (ValueError,TypeError): return None


def manaos_time(iso):
    if not iso: return "—"
    try:
        dt=datetime.fromisoformat(iso.replace('Z','+00:00')).astimezone(MANAUS)
        return dt.strftime('%d/%m %H:%M')
    except Exception: return iso


def normalize_status(status, completed=None):
    """Map provider-specific states to one canonical football status."""
    s=(status or '').upper().strip()
    if completed is True: return 'FINISHED'
    if s in {'LIVE','IN_PLAY','1H','2H','ET','P','INPROGRESS','IN_PROGRESS'}: return 'LIVE'
    if s in {'PAUSED','HT','HALFTIME','BREAK'}: return 'PAUSED'
    if s in {'FINISHED','FT','AET','PEN','POSTGAME','FINAL'}: return 'FINISHED'
    if s in {'POSTPONED','SUSPENDED','CANCELLED','CANCELED','ABANDONED'}:
        return 'CANCELLED' if s in {'CANCELLED','CANCELED'} else s
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
