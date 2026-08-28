from datetime import datetime
from zoneinfo import ZoneInfo

MANAUS = ZoneInfo('America/Manaus')

# Métricas individuais prioritárias do projeto.
PLAYER_DISPLAY_ORDER = ['goals','assists','shots','shots_on_target','passes_completed','tackles','fouls','was_fouled']
PLAYER_DISPLAY_LABELS = {
    'goals':'Gols','assists':'Assistências','shots':'Finalizações','shots_on_target':'Finalizações no gol',
    'passes_completed':'Passes certos','tackles':'Desarmes','fouls':'Faltas cometidas','was_fouled':'Faltas sofridas'
}

PLAYER_METRIC_ALIASES = {
    'goals':'goals','goal':'goals','goals_scored':'goals','total_goals':'goals',
    'assists':'assists','assist':'assists',
    'passes_completed':'passes_completed','accuratepasses':'passes_completed','accurate_passes':'passes_completed',
    'passesaccurate':'passes_completed','passes_accurate':'passes_completed','total_passes_completed':'passes_completed',
    'tackles':'tackles','total_tackles':'tackles','totaltackles':'tackles','matchstats.headers.tackles':'tackles',
    'effectivetackles':'tackles','effective_tackles':'tackles',
    'fouls':'fouls','foulscommitted':'fouls','fouls_committed':'fouls',
    'was_fouled':'was_fouled','fouled':'was_fouled','fouls_suffered':'was_fouled','fouls_suffered_total':'was_fouled',
    'shots':'shots','totalshots':'shots','total_shots':'shots','shots_total':'shots',
    'shots_on_target':'shots_on_target','shotsontarget':'shots_on_target','shots_on_goal':'shots_on_target',
    'shots_on_target_total':'shots_on_target'
}

POSITION_LABELS = {0:'Goleiro',1:'Defensor',2:'Meio-campista',3:'Atacante'}
PERCENT_METRICS = {'crosspct','longballpct','passpct','possessionpct','shotpct','tacklepct','shot_accuracy'}
STATUS_LABELS = {'SCHEDULED':'AGENDADO','LIVE':'EM ANDAMENTO','PAUSED':'INTERVALO','FINISHED':'FINALIZADO','POSTPONED':'ADIADO','SUSPENDED':'SUSPENSO','CANCELLED':'CANCELADO'}

# Mantém as métricas de partida existentes.
MATCH_DISPLAY_ORDER=['goals','shots','shots_on_target','woodwork','effectivetackles','corners','fouls','saves','player_throws','yellow_cards','red_cards','offsides','goal_kicks','passes_completed']
MATCH_DISPLAY_LABELS={'goals':'Gols','shots':'Finalizações totais','shots_on_target':'Finalizações no alvo','woodwork':'Finalizações na trave','effectivetackles':'Desarmes efetivos','corners':'Escanteios','fouls':'Faltas','saves':'Defesas do goleiro','player_throws':'Laterais','yellow_cards':'Cartões amarelos','red_cards':'Cartões vermelhos','offsides':'Impedimentos','goal_kicks':'Tiros de meta','passes_completed':'Passes certos'}
MATCH_METRIC_ALIASES={'goals':'goals','shots':'shots','totalshots':'shots','total_shots':'shots','shots_total':'shots','shots_on_target':'shots_on_target','shotsontarget':'shots_on_target','shots_on_goal':'shots_on_target','woodwork':'woodwork','shots_woodwork':'woodwork','shotswoodwork':'woodwork','effectivetackles':'effectivetackles','effective_tackles':'effectivetackles','totaltackles':'effectivetackles','total_tackles':'effectivetackles','corners':'corners','corner_kicks':'corners','woncorners':'corners','fouls':'fouls','foulscommitted':'fouls','fouls_committed':'fouls','saves':'saves','keeper_saves':'saves','goalkeeper_saves':'saves','player_throws':'player_throws','throws':'player_throws','throw_ins':'player_throws','yellowcards':'yellow_cards','yellow_cards':'yellow_cards','redcards':'red_cards','red_cards':'red_cards','offsides':'offsides','goal_kicks':'goal_kicks','goalkicks':'goal_kicks','passes_completed':'passes_completed','accuratepasses':'passes_completed','accurate_passes':'passes_completed','passesaccurate':'passes_completed'}

# Compatibilidade: nomes usados em outros módulos.
PLAYER_METRICS = {k:v for k,v in PLAYER_DISPLAY_LABELS.items()}
METRICS = {**MATCH_DISPLAY_LABELS}
SOURCE_PRIORITY={'FotMob':0,'ESPN':1,'API-Football':2,'Football-Data.org':3}

def _key(name): return str(name or '').strip().lower().replace(' ','_').replace('-','_')
def status_label(status): return STATUS_LABELS.get(str(status or '').upper(),str(status or '—'))
def metric_label(name,player=False):
    key=_key(name);return (PLAYER_METRICS if player else METRICS).get(key,key.replace('_',' ').title())
def position_label(position):
    try:return POSITION_LABELS.get(int(position),str(position or '—'))
    except (TypeError,ValueError):return str(position or '—')
def clean_number(value):
    if value is None:return None
    if isinstance(value,(int,float)):return float(value)
    try:return float(str(value).strip().replace('%','').replace(',','.'))
    except (ValueError,TypeError):return None
def format_metric_value(metric,value):
    if value is None:return '—'
    n=clean_number(value);key=_key(metric)
    if n is None:return str(value)
    if key in PERCENT_METRICS:return f'{n*100:.0f}%' if n<=1 else f'{n:.1f}%'
    return f'{n:.2f}'.rstrip('0').rstrip('.')
def canonical_match_metric(name):return MATCH_METRIC_ALIASES.get(_key(name))
def canonical_player_metric(name):return PLAYER_METRIC_ALIASES.get(_key(name))
def match_metric_label(name):return MATCH_DISPLAY_LABELS.get(canonical_match_metric(name) or _key(name),_key(name).replace('_',' ').title())
def player_metric_label(name):return PLAYER_DISPLAY_LABELS.get(canonical_player_metric(name) or _key(name),_key(name).replace('_',' ').title())
def source_rank(source):return SOURCE_PRIORITY.get(str(source or ''),99)
def choose_preferred_stat(rows):
    rows=[r for r in rows if r.get('value') is not None]
    return sorted(rows,key=lambda r:(source_rank(r.get('source')),str(r.get('source') or '')))[0] if rows else None
def manaos_time(iso):
    if not iso:return '—'
    try:return datetime.fromisoformat(iso.replace('Z','+00:00')).astimezone(MANAUS).strftime('%d/%m %H:%M')
    except Exception:return iso
def normalize_status(status,completed=None):
    s=(status or '').upper().strip()
    if completed is True:return 'FINISHED'
    if s in {'LIVE','IN_PLAY','1H','2H','ET','P','INPROGRESS','IN_PROGRESS'}:return 'LIVE'
    if s in {'PAUSED','HT','HALFTIME','BREAK'}:return 'PAUSED'
    if s in {'FINISHED','FT','AET','PEN','POSTGAME','FINAL'}:return 'FINISHED'
    if s in {'POSTPONED','SUSPENDED','CANCELLED','CANCELED','ABANDONED'}:return 'CANCELLED' if s in {'CANCELLED','CANCELED'} else s
    return 'SCHEDULED'
def normalize_metric(name):
    s=_key(name)
    return {'total_shots':'shots','shots_total':'shots','shots_on_goal':'shots_on_target','shotsontarget':'shots_on_target','corner_kicks':'corners','accurate_passes':'passes_completed','accuratepasses':'passes_completed','passesaccurate':'passes_completed','yellowcards':'yellow_cards','redcards':'red_cards','goalkeeper_saves':'saves','keeper_saves':'saves','shots_woodwork':'woodwork','shotswoodwork':'woodwork','effectivetackles':'effectivetackles','effective_tackles':'effectivetackles','totaltackles':'effectivetackles','total_tackles':'effectivetackles','goalkicks':'goal_kicks','goal_kicks':'goal_kicks','throws':'player_throws','throw_ins':'player_throws'}.get(s,s)
def average(values):
    vals=[clean_number(v) for v in values];vals=[v for v in vals if v is not None]
    return round(sum(vals)/len(vals),2) if vals else None
