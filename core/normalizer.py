from datetime import datetime
from zoneinfo import ZoneInfo

MANAUS = ZoneInfo("America/Manaus")

METRICS = {
    "goals":"Gols", "shots":"Finalizações", "shots_on_target":"Finalizações no alvo",
    "corners":"Escanteios", "passes_completed":"Passes certos", "possession":"Posse (%)",
    "fouls":"Faltas", "offsides":"Impedimentos", "yellow_cards":"Cartões amarelos",
    "red_cards":"Cartões vermelhos", "saves":"Defesas do goleiro", "woodwork":"Bola na trave",
    "goal_kicks":"Tiros de meta", "accuratecrosses":"Cruzamentos certos", "accuratelongballs":"Lançamentos certos",
    "accuratepasses":"Passes certos", "ballpossesion":"Posse de bola (%)", "big_chance":"Grandes chances",
    "big_chance_missed_title":"Grandes chances perdidas", "blocked_shots":"Finalizações bloqueadas",
    "blockedshots":"Finalizações bloqueadas", "clearances":"Cortes/Desarmes", "crosspct":"Precisão de cruzamentos (%)",
    "duel_won":"Duelos ganhos", "effectiveclearance":"Cortes efetivos", "effectivetackles":"Desarmes efetivos",
    "expected_goals":"Gols esperados (xG)", "expected_goals_non_penalty":"xG sem pênaltis",
    "expected_goals_on_target":"xG no alvo", "expected_goals_open_play":"xG em bola rolando",
    "expected_goals_set_play":"xG em bola parada", "foulscommitted":"Faltas cometidas",
    "interceptions":"Interceptações", "keeper_saves":"Defesas do goleiro", "longballpct":"Precisão de lançamentos (%)",
    "matchstats.headers.tackles":"Desarmes", "opposition_half_passes":"Passes no campo adversário",
    "own_half_passes":"Passes no próprio campo", "passes":"Passes", "passpct":"Precisão de passes (%)",
    "penaltykickgoals":"Gols de pênalti", "penaltykickshots":"Finalizações de pênalti", "player_throws":"Arremessos laterais",
    "possessionpct":"Posse de bola (%)", "shot_blocks":"Bloqueios de finalização", "shotpct":"Precisão das finalizações (%)",
    "shots_inside_box":"Finalizações dentro da área", "shots_outside_box":"Finalizações fora da área",
    "shots_woodwork":"Finalizações na trave", "shotsofftarget":"Finalizações para fora", "shotsontarget":"Finalizações no alvo",
    "tacklepct":"Precisão dos desarmes (%)", "totalclearance":"Cortes totais", "totalcrosses":"Cruzamentos totais",
    "totallongballs":"Lançamentos totais", "totalpasses":"Passes totais", "totalshots":"Finalizações totais",
    "totaltackles":"Desarmes totais", "touches_opp_box":"Toques na área adversária", "woncorners":"Escanteios ganhos",
    "yellowcards":"Cartões amarelos", "redcards":"Cartões vermelhos"
}

PLAYER_METRICS = {
    "accurate_crosses":"Cruzamentos certos", "aerials_won":"Duelos aéreos ganhos", "assists":"Assistências",
    "big_chance_created_team_title":"Grandes chances criadas", "big_chance_missed_title":"Grandes chances perdidas",
    "blocked_shots":"Finalizações bloqueadas", "chances_created":"Chances criadas", "clearances":"Cortes",
    "corners":"Escanteios", "defensive_actions":"Ações defensivas", "dispossessed":"Perdas de posse",
    "dribbled_past":"Driblado por adversário", "dribbles_succeeded":"Dribles certos", "duel_lost":"Duelos perdidos",
    "duel_won":"Duelos ganhos", "errors_led_to_goal":"Erros que resultaram em gol", "expected_assists":"Assistências esperadas (xA)",
    "expected_goals":"Gols esperados (xG)", "expected_goals_non_penalty":"xG sem pênaltis", "expected_goals_on_target_faced":"xG no alvo enfrentado",
    "expected_goals_on_target_variant":"xG no alvo", "fouls":"Faltas cometidas", "goals":"Gols", "goals_conceded":"Gols sofridos",
    "goals_prevented":"Gols evitados", "ground_duels_won":"Duelos no chão ganhos", "headed_clearance":"Cortes de cabeça",
    "interceptions":"Interceptações", "keeper_diving_save":"Defesas em mergulho", "keeper_high_claim":"Bolas aéreas agarradas",
    "keeper_sweeper":"Ações como goleiro-líbero", "long_balls_accurate":"Lançamentos certos", "matchstats.headers.tackles":"Desarmes",
    "minutes_played":"Minutos jogados", "offsides":"Impedimentos", "passes_completed":"Passes certos",
    "passes_into_final_third":"Passes para o terço final", "player_throws":"Arremessos laterais", "punches":"Socos/afastamentos",
    "rating_title":"Nota", "recoveries":"Recuperações", "saves":"Defesas", "saves_inside_box":"Defesas dentro da área",
    "shot_accuracy":"Precisão das finalizações (%)", "shot_blocks":"Finalizações bloqueadas", "shots":"Finalizações",
    "shots_woodwork":"Finalizações na trave", "shotsofftarget":"Finalizações para fora", "shotsontarget":"Finalizações no alvo",
    "touches":"Toques na bola", "touches_opp_box":"Toques na área adversária", "was_fouled":"Faltas sofridas", "xg_and_xa":"xG + xA"
}

POSITION_LABELS = {0:"Goleiro",1:"Defensor",2:"Meio-campista",3:"Atacante"}
PERCENT_METRICS = {"crosspct","longballpct","passpct","possessionpct","shotpct","tacklepct","shot_accuracy"}

STATUS_LABELS = {"SCHEDULED":"AGENDADO","LIVE":"EM ANDAMENTO","PAUSED":"INTERVALO","FINISHED":"FINALIZADO","POSTPONED":"ADIADO","SUSPENDED":"SUSPENSO","CANCELLED":"CANCELADO"}
DIAGNOSTIC_STATUS_LABELS = {"OK":"OK","ERROR":"ERRO","WARNING":"AVISO"}

def status_label(status): return STATUS_LABELS.get(str(status or "").upper(), str(status or "—"))
def diagnostic_status_label(status): return DIAGNOSTIC_STATUS_LABELS.get(str(status or "").upper(), str(status or "—"))
def metric_label(name, player=False):
    key=str(name or "").strip().lower().replace(" ","_").replace("-","_")
    return (PLAYER_METRICS if player else METRICS).get(key, METRICS.get(key, PLAYER_METRICS.get(key, key.replace("_"," ").title())))
def position_label(position):
    try: return POSITION_LABELS.get(int(position), str(position or "—"))
    except (TypeError,ValueError): return str(position or "—")
def clean_number(value):
    if value is None:return None
    if isinstance(value,(int,float)):return float(value)
    try:return float(str(value).strip().replace('%','').replace(',','.'))
    except (ValueError,TypeError):return None
def format_metric_value(metric,value):
    if value is None:return "—"
    n=clean_number(value)
    if n is None:return str(value)
    key=str(metric or "").lower()
    if key in PERCENT_METRICS:return f"{n*100:.0f}%" if n <= 1 else f"{n:.1f}%"
    return f"{n:.2f}".rstrip('0').rstrip('.')
def manaos_time(iso):
    if not iso:return "—"
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
    s=(name or '').lower().strip().replace(' ','_').replace('-','_')
    return {'total_shots':'shots','shots_total':'shots','shots_on_goal':'shots_on_target','corner_kicks':'corners','accurate_passes':'passes_completed','yellowcards':'yellow_cards','redcards':'red_cards','goalkeeper_saves':'saves','offsides':'offsides'}.get(s,s)
def average(values):
    vals=[clean_number(v) for v in values];vals=[v for v in vals if v is not None]
    return round(sum(vals)/len(vals),2) if vals else None
