from datetime import datetime
from zoneinfo import ZoneInfo
import re
MANAUS=ZoneInfo('America/Manaus')
PLAYER_DISPLAY_ORDER=['goals','assists','shots_on_target','shots','passes_completed','tackles','tackles_won','fouls','was_fouled','yellow_cards','red_cards']
PLAYER_DISPLAY_LABELS={'goals':'Gols','assists':'Assistências','shots_on_target':'Finalizações certas','shots':'Finalizações no gol','passes_completed':'Passes certos','tackles':'Desarmes','tackles_won':'Desarmes certos','fouls':'Faltas cometidas','was_fouled':'Faltas sofridas','yellow_cards':'Cartões amarelos','red_cards':'Cartões vermelhos'}
PLAYER_METRIC_ALIASES={'goals':'goals','goal':'goals','goals_scored':'goals','total_goals':'goals','assists':'assists','assist':'assists','goal_assists':'assists','assists_total':'assists','total_assists':'assists','shots':'shots','total_shots':'shots','shots_total':'shots','shotsattempted':'shots','shots_attempted':'shots','shot_attempts':'shots','shots_on_target':'shots_on_target','shotsontarget':'shots_on_target','shots_on_goal':'shots_on_target','shots_on_target_total':'shots_on_target','shotsontargettotal':'shots_on_target','shots_on_target_attempts':'shots_on_target','accurate_passes':'passes_completed','accuratepasses':'passes_completed','passes_accurate':'passes_completed','passesaccurate':'passes_completed','passes_completed':'passes_completed','completed_passes':'passes_completed','completions':'passes_completed','completion':'passes_completed','passing_completions':'passes_completed','passing_completion':'passes_completed','total_passes_completed':'passes_completed','accurate_pass':'passes_completed','passes':'passes_completed','total_passes':'passes_completed','completedpasses':'passes_completed','successful_passes':'passes_completed','successfulpasses':'passes_completed','tackles':'tackles','total_tackles':'tackles','totaltackles':'tackles','tackles_total':'tackles','effective_tackles':'tackles','effectivetackles':'tackles','tackles_won':'tackles_won','successful_tackles':'tackles_won','successfultackles':'tackles_won','won_tackles':'tackles_won','tackleswon':'tackles_won','matchstats_headers_tackles':'tackles','matchstats_headers_tackles_total':'tackles','fouls':'fouls','fouls_committed':'fouls','foulscommitted':'fouls','total_fouls':'fouls','fouls_committed_total':'fouls','was_fouled':'was_fouled','fouled':'was_fouled','fouls_suffered':'was_fouled','fouls_suffered_total':'was_fouled','yellow_card':'yellow_cards','yellow_cards':'yellow_cards','yellowcards':'yellow_cards','yellowcard':'yellow_cards','total_yellow_cards':'yellow_cards','yellow_cards_total':'yellow_cards','red_card':'red_cards','red_cards':'red_cards','redcards':'red_cards','redcard':'red_cards','total_red_cards':'red_cards','red_cards_total':'red_cards'}
POSITION_LABELS={0:'Goleiro',1:'Defensor',2:'Meio-campista',3:'Atacante','GK':'Goleiro','G':'Goleiro','GOALKEEPER':'Goleiro','GOALIE':'Goleiro','CB':'Zagueiro','RCB':'Zagueiro','LCB':'Zagueiro','DC':'Zagueiro','CENTRE_BACK':'Zagueiro','CENTER_BACK':'Zagueiro','D':'Defensor','DEFENDER':'Defensor','RB':'Lateral-direito','RWB':'Ala-direito','LD':'Lateral-direito','RIGHT_BACK':'Lateral-direito','RIGHT_WING_BACK':'Ala-direito','LB':'Lateral-esquerdo','LWB':'Ala-esquerdo','LE':'Lateral-esquerdo','LEFT_BACK':'Lateral-esquerdo','LEFT_WING_BACK':'Ala-esquerdo','DM':'Volante','CDM':'Volante','MDC':'Volante','DEFENSIVE_MIDFIELDER':'Volante','CM':'Meio-campista','CM-R':'Meio-campista','CM-L':'Meio-campista','MC':'Meio-campista','MIDFIELDER':'Meio-campista','AM':'Meia-atacante','CAM':'Meia-atacante','MOC':'Meia-atacante','ATTACKING_MIDFIELDER':'Meia-atacante','RM':'Meio-campista','LM':'Meio-campista','RW':'Ponta-direita','LW':'Ponta-esquerda','RF':'Atacante','LF':'Atacante','CF':'Centroavante','CF-L':'Centroavante','CF-R':'Centroavante','ST':'Atacante','FW':'Atacante','F':'Atacante','FORWARD':'Atacante','STRIKER':'Centroavante','CD-L':'Zagueiro','CD-R':'Zagueiro','LCB-L':'Zagueiro','RCB-R':'Zagueiro'}
PERCENT_METRICS={'crosspct','longballpct','passpct','possessionpct','shotpct','tacklepct','shot_accuracy'}
STATUS_LABELS={'SCHEDULED':'AGENDADO','LIVE':'EM ANDAMENTO','PAUSED':'INTERVALO','FINISHED':'FINALIZADO','POSTPONED':'ADIADO','SUSPENDED':'SUSPENSO','CANCELLED':'CANCELADO'}
MATCH_DISPLAY_ORDER=['goals','shots','shots_on_target','woodwork','effectivetackles','corners','fouls','saves','player_throws','yellow_cards','red_cards','offsides','goal_kicks','passes_completed']
MATCH_DISPLAY_LABELS={'goals':'Gols','shots':'Finalizações totais','shots_on_target':'Finalizações no alvo','woodwork':'Finalizações na trave','effectivetackles':'Desarmes efetivos','corners':'Escanteios','fouls':'Faltas','saves':'Defesas do goleiro','player_throws':'Laterais','yellow_cards':'Cartões amarelos','red_cards':'Cartões vermelhos','offsides':'Impedimentos','goal_kicks':'Tiros de meta','passes_completed':'Passes certos'}
MATCH_METRIC_ALIASES={'goals':'goals','shots':'shots','totalshots':'shots','total_shots':'shots','shots_total':'shots','shots_on_target':'shots_on_target','shotsontarget':'shots_on_target','shots_on_goal':'shots_on_target','woodwork':'woodwork','shots_woodwork':'woodwork','shotswoodwork':'woodwork','effectivetackles':'effectivetackles','effective_tackles':'effectivetackles','totaltackles':'effectivetackles','total_tackles':'effectivetackles','tackles':'effectivetackles','corners':'corners','corner_kicks':'corners','woncorners':'corners','fouls':'fouls','foulscommitted':'fouls','fouls_committed':'fouls','saves':'saves','keeper_saves':'saves','goalkeeper_saves':'saves','player_throws':'player_throws','throws':'player_throws','throw_ins':'player_throws','yellowcards':'yellow_cards','yellow_card':'yellow_cards','yellow_cards':'yellow_cards','redcards':'red_cards','red_card':'red_cards','red_cards':'red_cards','offsides':'offsides','goal_kicks':'goal_kicks','goalkicks':'goal_kicks','passes_completed':'passes_completed','accuratepasses':'passes_completed','accurate_passes':'passes_completed','passesaccurate':'passes_completed','passes':'passes_completed','total_passes':'passes_completed','completions':'passes_completed','passing_completions':'passes_completed'}
PLAYER_METRICS=PLAYER_DISPLAY_LABELS.copy();METRICS=MATCH_DISPLAY_LABELS.copy();SOURCE_PRIORITY={'FotMob':0,'ESPN':1,'API-Football':2,'Football-Data.org':3}
def _key(name):
 s=str(name or '').strip();s=re.sub(r'([a-z0-9])([A-Z])',r'\1_\2',s);return re.sub(r'[^A-Za-z0-9]+','_',s).strip('_').upper()
def status_label(status):return STATUS_LABELS.get(str(status or '').upper(),str(status or '—'))
def metric_label(name,player=False):
 key=_key(name).lower();return (PLAYER_METRICS if player else METRICS).get(key,key.replace('_',' ').title())
def position_label(position):
 if isinstance(position,dict):position=position.get('abbreviation') or position.get('displayName') or position.get('name')
 raw=str(position or '').strip();key=raw.upper().replace(' ','_')
 if key in POSITION_LABELS:return POSITION_LABELS[key]
 try:return POSITION_LABELS.get(int(position),raw or '—')
 except (TypeError,ValueError):return raw or '—'
def clean_number(value):
 if value is None:return None
 if isinstance(value,(int,float)):return float(value)
 try:return float(str(value).strip().replace('%','').replace(',','.'))
 except (ValueError,TypeError):return None
def format_metric_value(metric,value):
 if value is None:return '—'
 n=clean_number(value);key=_key(metric).lower()
 if key in PERCENT_METRICS:return f'{n*100:.0f}%' if n<=1 else f'{n:.1f}%'
 return f'{n:.2f}'.rstrip('0').rstrip('.') if n is not None else str(value)
def canonical_match_metric(name):return MATCH_METRIC_ALIASES.get(_key(name).lower())
def canonical_player_metric(name):return PLAYER_METRIC_ALIASES.get(_key(name).lower())
def match_metric_label(name):return MATCH_DISPLAY_LABELS.get(canonical_match_metric(name) or _key(name).lower(),_key(name).replace('_',' ').title())
def player_metric_label(name):return PLAYER_DISPLAY_LABELS.get(canonical_player_metric(name) or _key(name).lower(),_key(name).replace('_',' ').title())
def source_rank(source):return SOURCE_PRIORITY.get(str(source or ''),99)
def choose_preferred_stat(rows):
 rows=[r for r in rows if r.get('value') is not None];return sorted(rows,key=lambda r:(source_rank(r.get('source')),str(r.get('source') or '')))[0] if rows else None
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
 key=_key(name).lower()
 if key in PLAYER_METRIC_ALIASES:return PLAYER_METRIC_ALIASES[key]
 return MATCH_METRIC_ALIASES.get(key,key)
def average(values):
 vals=[clean_number(v) for v in values];vals=[v for v in vals if v is not None];return round(sum(vals)/len(vals),2) if vals else None
