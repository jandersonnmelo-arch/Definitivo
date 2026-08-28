import streamlit as st
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import pandas as pd
from core.db import init_db,get_matches,get_match,get_stats,get_players,get_diagnostics,usage_today,team_history,player_history_summary
from core.football import collect,enrich
from core.history import build_history_for_match
from core.engine import build_pre_match_analysis
from core.competitions import FIXED_COMPETITIONS,OPTIONAL_COMPETITIONS,selected_labels,canonical_competition_label
from core.normalizer import manaos_time,status_label,position_label,format_metric_value,MATCH_DISPLAY_ORDER,MATCH_DISPLAY_LABELS,PLAYER_DISPLAY_ORDER,PLAYER_DISPLAY_LABELS,canonical_match_metric,canonical_player_metric,choose_preferred_stat

st.set_page_config(page_title='Arena 360 • Futebol',page_icon='⚽',layout='centered',initial_sidebar_state='expanded')
init_db();MANAUS=ZoneInfo('America/Manaus');today=datetime.now(MANAUS).date()
fixed_labels=[x[0] for x in FIXED_COMPETITIONS];optional_labels=[x[0] for x in OPTIONAL_COMPETITIONS]

st.markdown('''<style>
.stApp{background:#060918}.block-container{max-width:760px;padding-top:1rem;padding-bottom:4rem}
.brand{display:flex;gap:12px;align-items:center;margin-bottom:20px}.mark{width:46px;height:46px;border-radius:14px;background:#b7ff27;color:#081000;display:grid;place-items:center;font-size:25px}
.eyebrow{font-size:11px;letter-spacing:2px;color:#b7ff27;font-weight:800}.brandname{font-size:21px;font-weight:850}.hero{font-size:31px;font-weight:850;line-height:1.08;margin:18px 0 10px}.hero span{color:#b7ff27}.small{font-size:12px;color:#858da7}
.fixed-comp{padding:7px 10px;margin:4px 0;border:1px solid #252c42;border-radius:10px;background:#10162a;font-size:12px}.window{padding:10px 12px;border:1px solid #252c42;border-radius:12px;background:#0d1325;font-size:12px;margin:8px 0 14px}
</style>''',unsafe_allow_html=True)

with st.sidebar:
    st.markdown('### 🏆 Campeonatos');st.caption('Lista fixa monitorada')
    with st.container(border=True):
        for label in fixed_labels:st.markdown(f'<div class="fixed-comp">{label}</div>',unsafe_allow_html=True)
    st.caption('Copa do Brasil reconhece também Copa Betano do Brasil.')
    st.markdown('#### ➕ Outros principais');optional_selected=st.multiselect('Adicionar ao monitoramento',optional_labels,default=[],key='optional_competitions')
    st.markdown('#### 📅 Janela de jogos');days=st.slider('Dias a partir de hoje',7,14,7,1,key='match_days');date_from=today;date_to=today+timedelta(days=days)
    st.markdown(f'<div class="window"><b>{date_from:%d/%m/%Y}</b> → <b>{date_to:%d/%m/%Y}</b><br><span class="small">Horários em Manaus • America/Manaus</span></div>',unsafe_allow_html=True)
    if st.button('🔄 Atualizar jogos',use_container_width=True,type='primary'):
        with st.spinner('Coletando partidas...'):rows=collect(date_from.isoformat(),date_to.isoformat(),competitions=selected_labels(optional_selected))
        st.session_state['last_collection_count']=len(rows);st.success(f'{len(rows)} partidas encontradas.');st.rerun()

selected_competitions=selected_labels(optional_selected)
st.markdown('<div class="brand"><div class="mark">🏟️</div><div><div class="eyebrow">PLACAR</div><div class="brandname">Arena 360 • Futebol</div></div></div>',unsafe_allow_html=True)
st.markdown('<div class="hero">Toda a emoção, <span>em um só lugar.</span></div>',unsafe_allow_html=True)
st.caption('Fontes → normalização → banco → histórico → enriquecimento → análise. O pré-jogo usa somente dados persistidos.')

all_matches=get_matches('Futebol',1000);window_matches=[]
for m in all_matches:
    try:local_date=datetime.fromisoformat((m.get('start_time') or '').replace('Z','+00:00')).astimezone(MANAUS).date()
    except Exception:continue
    if date_from<=local_date<=date_to and canonical_competition_label(m.get('competition')) in selected_competitions:window_matches.append(m)
window_matches.sort(key=lambda x:(x.get('start_time') or '',x.get('competition') or '',x.get('home_name') or ''))
st.markdown(f'### Partidas <span class="small">{len(window_matches)} eventos • {days} dias</span>',unsafe_allow_html=True)
for m in window_matches:
    if st.button(f'{m["home_name"]}  {m.get("home_score") if m.get("home_score") is not None else "·"} × {m.get("away_score") if m.get("away_score") is not None else "·"}  {m["away_name"]}',key=f'm_{m["id"]}',use_container_width=True):st.session_state['selected']=m['id']
    st.caption(f'🏆 {canonical_competition_label(m.get("competition"))} • 🕐 {manaos_time(m.get("start_time"))} • {status_label(m.get("status"))} • fonte(s): {m.get("source")}')

selected=st.session_state.get('selected')
if selected:
    m=get_match(selected)
    if m:
        st.divider();st.subheader(f'📊 {m["home_name"]} × {m["away_name"]}');st.caption(f'🏆 {canonical_competition_label(m.get("competition"))} • 🕐 {manaos_time(m.get("start_time"))} • {status_label(m.get("status"))}')
        stats=get_stats(selected);st.markdown('### 📈 Estatísticas da partida')
        if stats or m.get('home_score') is not None or m.get('away_score') is not None:
            rows=[]
            for canonical in MATCH_DISPLAY_ORDER:
                if canonical=='goals':home=m.get('home_score');away=m.get('away_score')
                else:
                    hr=choose_preferred_stat([r for r in stats if r.get('team_id')==m['home_id'] and canonical_match_metric(r.get('metric'))==canonical]);ar=choose_preferred_stat([r for r in stats if r.get('team_id')==m['away_id'] and canonical_match_metric(r.get('metric'))==canonical]);home=hr.get('value') if hr else None;away=ar.get('value') if ar else None
                total=home+away if isinstance(home,(int,float)) and isinstance(away,(int,float)) else None;rows.append({'Indicador':MATCH_DISPLAY_LABELS[canonical],'Casa':format_metric_value(canonical,home),'Fora':format_metric_value(canonical,away),'Total':format_metric_value(canonical,total)})
            st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
        else:st.info('Sem estatísticas persistidas para esta partida. O sistema não inventa valores.')

        before=m.get('start_time') or '';home_hist=team_history(m['home_id'],before,10) if m.get('home_id') else [];away_hist=team_history(m['away_id'],before,10) if m.get('away_id') else []
        st.markdown('### 📚 Histórico das equipes');c1,c2=st.columns(2);c1.metric(m['home_name'],len(home_hist));c2.metric(m['away_name'],len(away_hist))
        for tname,hist in ((m['home_name'],home_hist),(m['away_name'],away_hist)):
            with st.expander(f'⚽ Últimos {len(hist)} jogos — {tname}',expanded=False):
                if hist:st.dataframe(pd.DataFrame([{'Data':manaos_time(x.get('start_time')),'Competição':canonical_competition_label(x.get('competition')),'Jogo':f'{x["home_name"]} {x.get("home_score","-")} × {x.get("away_score","-")} {x["away_name"]}'} for x in hist]),hide_index=True,use_container_width=True)
                else:st.info('Nenhum jogo histórico persistido.')

        if m.get('status')=='SCHEDULED':
            if st.button('📚 Atualizar histórico + estatísticas + jogadores',key=f'h_{selected}',use_container_width=True,type='primary'):
                with st.spinner('Preparando 10 jogos de cada equipe, estatísticas e jogadores...'):
                    result=build_history_for_match(m)
                if not isinstance(result,dict):
                    st.error('O enriquecimento do histórico não retornou um resultado válido. Verifique o diagnóstico do sistema.')
                else:
                    home_n=result.get('home_matches') or 0
                    away_n=result.get('away_matches') or 0
                    stats_n=result.get('stats_records') or 0
                    player_n=result.get('player_records') or 0
                    current_players=result.get('current_players') or []
                    st.success(f'Histórico: {home_n} + {away_n} jogos • {stats_n} estatísticas • {player_n} registros individuais • {len(current_players)} jogadores da partida.')
                st.rerun()
        elif len(home_hist)<10 or len(away_hist)<10:
            if st.button('📚 Completar histórico',key=f'h_{selected}',use_container_width=True):
                result=build_history_for_match(m);st.success(f'Histórico atualizado: {(result or {}).get("stats_records") or 0} estatísticas e {(result or {}).get("player_records") or 0} individuais.');st.rerun()

        if m.get('status')=='SCHEDULED':
            analysis=build_pre_match_analysis(m);p=analysis['probabilities'];st.subheader('🔮 Análise pré-jogo')
            if p['home'] is None:st.info('Ainda não há histórico suficiente. Atualize o histórico acima.')
            else:
                c1,c2,c3=st.columns(3);c1.metric('Casa',f'{p["home"]}%');c2.metric('Empate',f'{p["draw"]}%');c3.metric('Fora',f'{p["away"]}%')
            st.caption(f'Amostra: {analysis["sample_home"]} casa / {analysis["sample_away"]} fora • xG projetado: {analysis["xg_home"] if analysis["xg_home"] is not None else "—"} × {analysis["xg_away"] if analysis["xg_away"] is not None else "—"}.')

            st.markdown('### 📊 Base estatística do palpite')
            metric_rows=[]
            for key,label in [('goals_for','Gols feitos'),('goals_against','Gols sofridos'),('shots','Finalizações'),('shots_on_target','Finalizações no alvo'),('corners','Escanteios'),('fouls','Faltas'),('yellow_cards','Cartões amarelos'),('offsides','Impedimentos'),('saves','Defesas do goleiro')]:
                hv=analysis['home'].get(key);av=analysis['away'].get(key)
                if hv is None and av is None:continue
                metric_rows.append({'Indicador':label,'Casa — média':format_metric_value(key,hv),'Fora — média':format_metric_value(key,av),'Amostra':f'{analysis["home"].get(key+"_sample",0)}/{analysis["away"].get(key+"_sample",0)}'})
            if metric_rows:st.dataframe(pd.DataFrame(metric_rows),hide_index=True,use_container_width=True)
            else:st.warning('Há jogos históricos, mas as métricas detalhadas ainda não foram persistidas.')

            mk=analysis['markets'];st.markdown('### 🎯 Palpites estatísticos');rows=[]
            for label,key in [('Gols','gols'),('Finalizações','finalizacoes'),('Finalizações no alvo','finalizacoes_no_alvo'),('Escanteios','escanteios'),('Faltas','faltas'),('Cartões amarelos','cartoes_amarelos'),('Impedimentos','impedimentos'),('Defesas','defesas')]:
                obj=mk.get(key) or {};lines=obj.get('lines') or []
                if obj.get('total_expected') is None and not lines:continue
                for line,prob in lines.items():rows.append({'Mercado':label,'Linha':f'Over {line}','Probabilidade':f'{prob}%','Média projetada':obj.get('total_expected')})
            if rows:st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
            else:st.info('Sem amostra estatística suficiente para mercados de finalizações, escanteios, cartões etc.')
            if mk.get('ambas_marcam') is not None:st.metric('🤝 Ambas marcam — SIM',f'{mk["ambas_marcam"]}%')
            exact=(mk.get('gols') or {}).get('exact_total') or {}
            if exact:
                st.markdown('#### ⚽ Distribuição de gols');st.dataframe(pd.DataFrame([{'Total de gols':k,'Probabilidade':f'{v}%'} for k,v in exact.items()]),hide_index=True,use_container_width=True)
            st.caption('Probabilidades de mercados estatísticos usam Poisson sobre médias históricas persistidas. Ausência de dado não vira zero.')

            for tid,tname in ((m.get('home_id'),m.get('home_name')),(m.get('away_id'),m.get('away_name'))):
                if not tid:continue
                summary=player_history_summary(tid,before,20);st.markdown(f'#### 👥 Jogadores da análise — {tname}')
                if summary:st.dataframe(pd.DataFrame([{'Jogador':x['name'],'Jogos':x['matches'],'Gols':format_metric_value('goals',x['goals']),'Assistências':format_metric_value('assists',x['assists']),'Finalizações':format_metric_value('shots',x['shots']),'No alvo':format_metric_value('shots_on_target',x['shots_on_target']),'Passes certos':format_metric_value('passes_completed',x['passes_completed']),'Desarmes':format_metric_value('tackles',x['tackles'])} for x in summary]),hide_index=True,use_container_width=True)
                else:st.info('Nenhum dado individual histórico persistido para esta equipe.')

        players=get_players(selected);unique_players={x['id']:x for x in players};st.subheader(f'👥 Jogadores da partida • {len(unique_players)}')
        if players and m['status']!='SCHEDULED':
            teams={}
            for p in players:teams.setdefault(p.get('team_id'),[]).append(p)
            for tid in [m['home_id'],m['away_id']]+[x for x in teams if x not in (m['home_id'],m['away_id'])]:
                plist=teams.get(tid,[])
                if not plist:continue
                team_name=m['home_name'] if tid==m['home_id'] else m['away_name'] if tid==m['away_id'] else 'Equipe';st.markdown(f'#### {team_name}')
                for pid in sorted({p['id'] for p in plist},key=lambda x:next((p['name'] for p in plist if p['id']==x),'')):
                    p0=next(p for p in plist if p['id']==pid);pstats=[p for p in plist if p['id']==pid]
                    with st.expander(f'👤 {p0["name"]} • {position_label(p0.get("position"))}',expanded=False):
                        table=[]
                        for canonical in PLAYER_DISPLAY_ORDER:
                            chosen=choose_preferred_stat([r for r in pstats if canonical_player_metric(r.get('metric'))==canonical]);value=chosen.get('value') if chosen else None;table.append({'Indicador':PLAYER_DISPLAY_LABELS[canonical],'Valor':format_metric_value(canonical,value)})
                        st.dataframe(pd.DataFrame(table),hide_index=True,use_container_width=True)
        elif m['status']!='SCHEDULED':st.info('Nenhum dado individual persistido para esta partida.')
        if m['status']!='SCHEDULED' and st.button('🧩 Enriquecer esta partida',key=f'e_{selected}',use_container_width=True):
            with st.spinner('Enriquecendo com fontes disponíveis...'):n=enrich([m])
            st.success(f'Enriquecimento concluído: {n} registros.');st.rerun()

st.divider()
with st.expander('🩺 Diagnóstico do sistema'):
    u=usage_today('API-Football');st.caption(f'API-Football: {u.get("calls",0)} chamadas hoje • proteção 80/dia e 8/min • cache ativo.')
    ds=get_diagnostics(50)
    if ds:st.dataframe(pd.DataFrame(ds)[['created_at','stage','source','status','message']],hide_index=True,use_container_width=True)
    else:st.info('Nenhum diagnóstico registrado ainda.')