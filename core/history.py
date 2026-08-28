from datetime import datetime, timedelta, timezone
import re, unicodedata
from providers.football_data import FootballDataProvider
from providers.fotmob import FotMobProvider
from providers.espn import ESPNProvider
from core.db import get_team_provider_id, get_provider_id, upsert_match, team_history, history_coverage, add_diagnostic as _db_add_diagnostic, upsert_match_stats, upsert_players, upsert_player_stats, get_players, get_stats, get_match
from core.data_quality import reconcile_database
from core.ai_db import init_ai_db, save_match_sample
from core.engine import build_pre_match_analysis

HISTORY_MATCHES_PER_TEAM = 10
HISTORY_DAYS = 180
PRESENCE_METRIC = '__player_presence__'

TEAM_ALIASES = {
    'bayer leverkusen':'bayer 04 leverkusen','bayer 04':'bayer 04 leverkusen','bayern munich':'bayern munchen','bayern munchen fc':'bayern munchen','fc bayern munchen':'bayern munchen',
    'atletico mineiro':'atletico mineiro','atletico mg':'atletico mineiro','ca mineiro':'atletico mineiro','clube atletico mineiro':'atletico mineiro','cam':'atletico mineiro',
    'atletico paranaense':'athletico paranaense','athletico paranaense':'athletico paranaense','athletico pr':'athletico paranaense','cap':'athletico paranaense',
    'flamengo':'flamengo','flamengo rj':'flamengo','cr flamengo':'flamengo','palmeiras':'palmeiras','se palmeiras':'palmeiras','sao paulo':'sao paulo','sao paulo fc':'sao paulo',
    'corinthians':'corinthians','corinthians paulista':'corinthians','sport corinthians paulista':'corinthians','sport club corinthians paulista':'corinthians',
    'santos':'santos','santos fc':'santos','gremio':'gremio','gremio fbpa':'gremio','internacional':'internacional','sport club internacional':'internacional',
    'cruzeiro':'cruzeiro','cruzeiro esporte clube':'cruzeiro','botafogo':'botafogo','botafogo fr':'botafogo','fluminense':'fluminense','vasco da gama':'vasco da gama','vasco':'vasco da gama',
    'bahia':'bahia','ec bahia':'bahia','vitoria':'vitoria','fortaleza':'fortaleza','ceara':'ceara','sport recife':'sport recife','sport':'sport recife',
    'bragantino':'red bull bragantino','red bull bragantino':'red bull bragantino','red bull brasil':'red bull bragantino',
    'racing santander':'real racing club de santander','racing club de santander':'real racing club de santander','real racing':'real racing club de santander','real racing club de santander':'real racing club de santander','real racing de santander':'real racing club de santander',
    'sporting clube de portugal':'sporting portugal','clube de portugal':'sporting portugal','sporting portugal':'sporting portugal','sporting cp':'sporting portugal','sporting lisbon':'sporting portugal',
}

def add_diagnostic(stage,status,message,source=None,match_id=None):
    try:_db_add_diagnostic(stage,status,message,source,match_id)
    except Exception:pass

def _parse_start(value):
    if not value:return None
    try:return datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except Exception:return None

def _norm_name(value):
    s=unicodedata.normalize('NFKD',str(value or '')).encode('ascii','ignore').decode().lower();s=re.sub(r'[^a-z0-9]+',' ',s).strip()
    if s in TEAM_ALIASES:return TEAM_ALIASES[s]
    if s in {'ca mineiro','atletico mg','clube atletico mineiro','atletico mineiro'}:return 'atletico mineiro'
    if s=='cam':return 'atletico mineiro'
    s=re.sub(r'\b(fc|cf|sc|ec|ac|club|football|futbol)\b',' ',s);s=re.sub(r'[^a-z0-9]+',' ',s).strip();return TEAM_ALIASES.get(s,s)

def _same_team(a,b):
    a,b=_norm_name(a),_norm_name(b);return bool(a and b and (a==b or a in b or b in a))

def _history_matches_for_team(team_id,before_iso,limit=HISTORY_MATCHES_PER_TEAM):return team_history(team_id,before_iso,limit)

def _collect_team_history_from_football_data(team_id,before_iso,days=HISTORY_DAYS):
    provider=FootballDataProvider()
    if not provider.available():return []
    provider_id=get_team_provider_id(team_id,provider.name)
    if not provider_id:return []
    before=_parse_start(before_iso) or datetime.now(timezone.utc)
    try:rows=provider.team_matches(provider_id,(before-timedelta(days=days)).date().isoformat(),before.date().isoformat(),limit=100)
    except Exception as e:add_diagnostic('historico','ERROR',f'{provider.name}: {e}',provider.name);return []
    for m in rows:upsert_match(m)
    add_diagnostic('historico','OK',f'{provider.name}: {len(rows)} partidas históricas coletadas para a equipe',provider.name);return rows

def _collect_team_history_from_espn(team_name,before_iso,days=120):
    provider=ESPNProvider();before=_parse_start(before_iso) or datetime.now(timezone.utc);cur,end,rows=before.date()-timedelta(days=days),before.date(),[]
    while cur<=end:
        try:
            for m in provider.matches(cur.isoformat(),cur.isoformat(),None):
                if _same_team(team_name,m.get('home_name')) or _same_team(team_name,m.get('away_name')):upsert_match(m);rows.append(m)
        except Exception as e:add_diagnostic('historico','ERROR',f'ESPN fixtures: {e}',provider.name)
        cur+=timedelta(days=1)
    add_diagnostic('historico','OK',f'ESPN: {len(rows)} partidas históricas coletadas para {team_name}',provider.name);return rows

def _resolve_espn_event_id(match):
    provider=ESPNProvider();existing=get_provider_id(match.get('id'),provider.name)
    if existing:
        add_diagnostic('diagnostico_jogadores','OK',f'ESPN: ID do evento recuperado do banco ({existing})',provider.name,match.get('id'));return existing
    dt=_parse_start(match.get('start_time'))
    if not dt:return None
    dates=[]
    for delta in (-1,0,1):
        d=(dt+timedelta(days=delta)).date().isoformat()
        if d not in dates:dates.append(d)
    try:
        candidates=0
        for d in dates:
            rows=provider.matches(d,d,None);candidates+=len(rows)
            for m in rows:
                if _same_team(match.get('home_name'),m.get('home_name')) and _same_team(match.get('away_name'),m.get('away_name')):return m.get('provider_match_id')
                if _same_team(match.get('home_name'),m.get('away_name')) and _same_team(match.get('away_name'),m.get('home_name')):return m.get('provider_match_id')
        add_diagnostic('diagnostico_jogadores','INFO',f'ESPN: nenhum evento encontrado em +/-1 dia; candidatos={candidates} para {match.get("home_name")} x {match.get("away_name")}',provider.name,match.get('id'))
    except Exception as e:add_diagnostic('diagnostico_jogadores','ERROR',f'ESPN resolver: {e}',provider.name,match.get('id'))
    return None

def _presence_rows(players,pstats):
    out=list(pstats or []);existing={(str(r.get('player_id')),r.get('source')) for r in out if r.get('metric')!=PRESENCE_METRIC}
    for p in players or []:
        key=(str(p.get('id')),p.get('source','unknown'))
        if p.get('id') is not None and key not in existing:out.append({'player_id':p['id'],'metric':PRESENCE_METRIC,'value':1.0,'source':p.get('source','unknown')});existing.add(key)
    return out

def _real_player_stats(rows):return [r for r in (rows or []) if r.get('metric')!=PRESENCE_METRIC and r.get('value') is not None]

def _persist_detail(match,provider,d):
    stats=d.get('stats',[]) or [];players=[]
    for p in d.get('players',[]) or []:
        p=dict(p);p['source']=provider.name;p['match_id']=match['id'];players.append(p)
    pstats=[]
    for row in d.get('player_stats',[]) or []:
        row=dict(row);row['source']=provider.name;pstats.append(row)
    real_stats=_real_player_stats(pstats);pstats=_presence_rows(players,pstats)
    if stats:upsert_match_stats(match['id'],stats)
    if players:upsert_players(players)
    if pstats:upsert_player_stats(match['id'],pstats)
    return len(stats),len(players),len(real_stats),len([r for r in pstats if r.get('metric')==PRESENCE_METRIC])

def _diagnose_source_players(match,provider,detail,stage='diagnostico_jogadores'):
    players=detail.get('players',[]) or [];pstats=detail.get('player_stats',[]) or [];real_stats=_real_player_stats(pstats);presence=len([r for r in pstats if r.get('metric')==PRESENCE_METRIC]);names=[str(p.get('name') or 'Sem nome') for p in players[:8]];sample=', '.join(names) if names else 'nenhum nome retornado'
    add_diagnostic(stage,'OK' if players else 'INFO',f'{provider.name}: jogadores={len(players)}, estatísticas individuais reais={len(real_stats)}, presença={presence}, amostra=[{sample}]',provider.name,match.get('id'))

def _enrich_match_details(match,stage='historico'):
    total_stats=total_players=total_pstats=0;success=False
    espn=ESPNProvider()
    try:
        eid=_resolve_espn_event_id(match)
        if eid:
            d=espn.match_details(eid);_diagnose_source_players(match,espn,d);a,b,c,presence=_persist_detail(match,espn,d);total_stats+=a;total_players+=b;total_pstats+=c;add_diagnostic(stage,'OK',f'ESPN: {a} estatísticas, {b} jogadores, {c} estatísticas individuais reais, {presence} presenças',espn.name,match['id']);success|=bool(a or b or c or presence)
        else:add_diagnostic('diagnostico_jogadores','INFO','ESPN: partida não localizada para o teste isolado',espn.name,match.get('id'))
    except Exception as e:add_diagnostic('diagnostico_jogadores','ERROR',f'ESPN detalhes: {e}',espn.name,match.get('id'))
    fotmob=FotMobProvider()
    try:
        d=fotmob.match_details(match);_diagnose_source_players(match,fotmob,d);a,b,c,presence=_persist_detail(match,fotmob,d);total_stats+=a;total_players+=b;total_pstats+=c;add_diagnostic(stage,'OK',f'FotMob: {a} estatísticas, {b} jogadores, {c} estatísticas individuais reais, {presence} presenças',fotmob.name,match['id']);success|=bool(a or b or c or presence)
    except Exception as e:add_diagnostic('diagnostico_jogadores','ERROR',f'FotMob detalhes: {e}',fotmob.name,match.get('id'))
    return {'success':success,'stats':total_stats,'players':total_players,'player_stats':total_pstats}

def _enrich_historical_match(match):return _enrich_match_details(match,'historico')

def _has_real_player_stats(match_id):
    rows=get_players(match_id);return any(r.get('metric')!=PRESENCE_METRIC and r.get('value') is not None for r in rows)

def _has_required_team_metrics(match_id):
    rows=get_stats(match_id);values={}
    for r in rows:
        metric=str(r.get('metric'));value=r.get('value')
        if value is None:continue
        try:value=float(value)
        except Exception:continue
        values.setdefault(metric,[]).append(value)
    return bool(values.get('passes_completed')) and any(v>0 for v in values['passes_completed']) and bool(values.get('effectivetackles')) and any(v>0 for v in values['effectivetackles'])

def _save_ai_sample(match,training_ready):
    try:
        analysis=build_pre_match_analysis(match)
        save_match_sample(match,analysis,training_ready=training_ready)
        return True
    except Exception as e:
        add_diagnostic('ia_dataset','ERROR',f'Falha ao salvar amostra da IA: {e}','SYSTEM',match.get('id'))
        return False

def build_history_for_match(match,matches_per_team=HISTORY_MATCHES_PER_TEAM,days=HISTORY_DAYS):
    init_ai_db();reconcile_database()
    before_iso=match.get('start_time') or datetime.now(timezone.utc).isoformat()
    team_ids=[x for x in (match.get('home_id'),match.get('away_id')) if x]
    for team_id in team_ids:
        if history_coverage(team_id,before_iso)<matches_per_team:_collect_team_history_from_football_data(team_id,before_iso,days)
        hist=_history_matches_for_team(team_id,before_iso,matches_per_team)
        if len(hist)<matches_per_team:
            team_name=match['home_name'] if team_id==match.get('home_id') else match['away_name']
            _collect_team_history_from_espn(team_name,before_iso,120)

    reconciliation=reconcile_database(force=True)
    add_diagnostic('qualidade_dados','OK',f'Reconciliação pós-coleta: equipes={reconciliation.get("teams_merged",0)}, jogadores={reconciliation.get("players_merged",0)}, estatísticas migradas={reconciliation.get("stats_migrated",0)}, duplicadas removidas={reconciliation.get("stats_deduped",0)}','SYSTEM',match.get('id'))

    # A reconciliação pode substituir os IDs das equipes. Nunca continue usando
    # os IDs capturados antes dela: recarregamos a partida e trabalhamos com os
    # IDs canônicos atualmente persistidos no banco.
    fresh_match=get_match(match.get('id')) or match
    before_iso=fresh_match.get('start_time') or before_iso
    team_ids=[x for x in (fresh_match.get('home_id'),fresh_match.get('away_id')) if x]
    add_diagnostic('identidade_equipes','OK',f'IDs canônicos após reconciliação: casa={fresh_match.get("home_id")}, fora={fresh_match.get("away_id")}', 'SYSTEM',fresh_match.get('id'))

    historical_pool=[]
    for team_id in team_ids:
        historical_pool.extend(_history_matches_for_team(team_id,before_iso,matches_per_team))
    historical=[];seen=set()
    for h in sorted(historical_pool,key=lambda x:x.get('start_time') or '',reverse=True):
        if h['id'] not in seen:
            historical.append(h);seen.add(h['id'])
    historical=historical[:matches_per_team*2]

    enriched=stats_records=player_records=player_matches=0
    for h in historical:
        if not (get_stats(h['id']) and _has_real_player_stats(h['id']) and _has_required_team_metrics(h['id'])):
            r=_enrich_historical_match(h)
            if r['success']:
                enriched+=1;stats_records+=r['stats'];player_records+=r['player_stats']
                if r['players'] or r['player_stats']:player_matches+=1
        _save_ai_sample(h,training_ready=(h.get('status')=='FINISHED' and h.get('home_score') is not None and h.get('away_score') is not None))

    reconciliation2=reconcile_database(force=True)
    if any(reconciliation2.values()):add_diagnostic('qualidade_dados','OK',f'Reconciliação pós-enriquecimento: equipes={reconciliation2.get("teams_merged",0)}, jogadores={reconciliation2.get("players_merged",0)}, estatísticas migradas={reconciliation2.get("stats_migrated",0)}, duplicadas removidas={reconciliation2.get("stats_deduped",0)}','SYSTEM',fresh_match.get('id'))

    # Pode haver nova alteração de identidade após o enriquecimento. Recarrega
    # novamente antes de enriquecer a partida selecionada e antes dos contadores.
    fresh_match=get_match(fresh_match.get('id')) or fresh_match
    current=_enrich_match_details(fresh_match,'partida')
    player_records+=current['player_stats'];stats_records+=current['stats']
    if current['players']:player_matches+=1
    _save_ai_sample(fresh_match,training_ready=(fresh_match.get('status')=='FINISHED' and fresh_match.get('home_score') is not None and fresh_match.get('away_score') is not None))
    reconcile_database(force=True)

    final_match=get_match(fresh_match.get('id')) or fresh_match
    final_before=final_match.get('start_time') or before_iso
    final_team_ids=[x for x in (final_match.get('home_id'),final_match.get('away_id')) if x]
    home_n=len(_history_matches_for_team(final_team_ids[0],final_before,matches_per_team)) if len(final_team_ids)>0 else 0
    away_n=len(_history_matches_for_team(final_team_ids[1],final_before,matches_per_team)) if len(final_team_ids)>1 else 0
    return {'home_matches':home_n,'away_matches':away_n,'historical_matches':len(historical),'player_matches_enriched':player_matches,'stats_records':stats_records,'player_records':player_records,'current_players':current['players'],'current_stats':current['stats']}
