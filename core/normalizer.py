METRICS={'shots':'Finalizações','shots_on_target':'Finalizações no alvo','corners':'Escanteios','possession':'Posse','passes_completed':'Passes certos','offsides':'Impedimentos','yellow_cards':'Cartões amarelos','red_cards':'Cartões vermelhos','fouls':'Faltas','woodwork':'Bola na trave'}
def clean_number(v):
    if v in (None,'','-','—'): return None
    try:return float(v)
    except:return None
def normalize_stat(metric,value): return {'metric':metric,'value':clean_number(value),'label':METRICS.get(metric,metric)}
def normalize_match(raw): return {k:raw.get(k) for k in ('id','sport','competition','season','start_time','status','minute','home','away','score','source')}
