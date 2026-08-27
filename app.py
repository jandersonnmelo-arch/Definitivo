import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from core.db import init_db,get_matches,get_match,get_stats,get_players,get_diagnostics,usage_today
from core.football import collect,enrich
from core.engine import build_pre_match_analysis
from core.normalizer import (
    manaos_time,status_label,diagnostic_status_label,position_label,format_metric_value,
    MATCH_DISPLAY_ORDER,MATCH_DISPLAY_LABELS,PLAYER_DISPLAY_ORDER,PLAYER_DISPLAY_LABELS,
    canonical_match_metric,canonical_player_metric,choose_preferred_stat
)

st.set_page_config(page_title='Arena 360 • Futebol',page_icon='⚽',layout='centered',initial_sidebar_state='collapsed')
init_db();MANAUS=ZoneInfo('America/Manaus')

st.markdown('''<style>
.stApp{background:#060918}.block-container{max-width:760px;padding-top:1rem;padding-bottom:4rem}
.brand{display:flex;gap:12px;align-items:center;margin-bottom:20px}.mark{width:46px;height:46px;border-radius:14px;background:#b7ff27;color:#081000;display:grid;place-items:center;font-size:25px}.eyebrow{font-size:11px;letter-spacing:2px;color:#b7ff27;font-weight:800}.brandname{font-size:21px;font-weight:850}.hero{font-size:31px;font-weight:850;line-height:1.08;margin:18px 0 10px}.hero span{color:#b7ff27}.small{font-size:12px;color:#858da7}.section{display:flex;justify-content:space-between;align-items:end;margin:26px 0 10px;font-weight:800;font-size:18px}.card{border:1px solid #20263b;border-radius:20px;padding:16px;margin:10px 0;background:#0c1021}.live{border-color:#a7ed37}.score{font-size:26px;font-weight:900}
</style>''',unsafe_allow_html=True)
st.markdown('<div class="brand"><div class="mark">🏟️</div><div><div class="eyebrow">PLACAR</div><div class="brandname">Arena 360 • Futebol</div></div></div>',unsafe_allow_html=True)
st.markdown('<div class="hero">Toda a emoção, <span>em um só lugar.</span></div>',unsafe_allow_html=True)
st.caption('Arquitetura: fontes → normalização → identidade canônica → banco → cache → enriquecimento → análise. A análise não consulta APIs.')

with st.expander('📡 Coleta de dados',expanded=False):
    today=datetime.now(MANAUS).date();d1=st.date_input('De',today,key='d1');d2=st.date_input('Até',today,key='d2');comp=st.text_input('Competição (opcional)','',placeholder='Ex.: Brasileirão')
    if st.button('🔄 Coletar partidas',use_container_width=True):
        with st.spinner('Consultando fontes de calendário...'):rows=collect(d1.isoformat(),d2.isoformat(),comp or None)
        st.success(f'{len(rows)} partidas processadas.')
    st.markdown('**Papéis das fontes**');st.caption('🟢 ESPN + Football-Data.org = calendário/base. 🟡 FotMob = estatísticas + jogadores. 🔵 API-Football = enriquecimento operacional do dia, sem formar banco histórico.')

matches=get_matches('Futebol',100);live=[m for m in matches if m['status'] in ('LIVE','PAUSED')]
if live:
    m=live[0];st.markdown('<div class="section"><span>🔴 Destaque agora</span><span class="small">ao vivo</span></div>',unsafe_allow_html=True);st.markdown(f'<div class="card live"><div class="small">{m.get("competition") or "Futebol"} • {m.get("minute") or ""}’</div><div>{m["home_name"]} <span class="score">{m.get("home_score","-")} : {m.get("away_score","-")}</span> {m["away_name"]}</div></div>',unsafe_allow_html=True)
st.markdown(f'<div class="section"><span>Partidas</span><span class="small">{len(matches)} eventos</span></div>',unsafe_allow_html=True)
if not matches:st.info('Nenhuma partida persistida ainda. Use “Coleta de dados”.')
for m in matches:
    if st.button(f'{m["home_name"]}  {m.get("home_score") if m.get("home_score") is not None else "·"} × {m.get("away_score") if m.get("away_score") is not None else "·"}  {m["away_name"]}',key=f'm_{m["id"]}',use_container_width=True):st.session_state['selected']=m['id']
    st.caption(f'{m.get("competition") or "Futebol"} • {manaos_time(m.get("start_time"))} • {status_label(m.get("status"))} • fonte(s): {m.get("source")}')

selected=st.session_state.get('selected')
if selected:
    m=get_match(selected);st.divider();st.subheader(f'📊 {m["home_name"]} × {m["away_name"]}')
    st.caption(f'{m.get("competition") or "Futebol"} • {manaos_time(m.get("start_time"))} • {status_label(m.get("status"))}')
    stats=get_stats(selected)

    # Estatísticas da partida: conjunto fechado, uma linha por indicador,
    # Casa + Fora + Total. Valores de fontes diferentes nunca são somados.
    st.markdown('### 📈 Estatísticas da partida')
    if stats or m.get('home_score') is not None or m.get('away_score') is not None:
        rows=[]
        for canonical in MATCH_DISPLAY_ORDER:
            if canonical=='goals':
                home=m.get('home_score');away=m.get('away_score')
            else:
                home_rows=[r for r in stats if r.get('team_id')==m['home_id'] and canonical_match_metric(r.get('metric'))==canonical]
                away_rows=[r for r in stats if r.get('team_id')==m['away_id'] and canonical_match_metric(r.get('metric'))==canonical]
                home_row=choose_preferred_stat(home_rows);away_row=choose_preferred_stat(away_rows)
                home=home_row.get('value') if home_row else None
                away=away_row.get('value') if away_row else None
            total=home+away if isinstance(home,(int,float)) and isinstance(away,(int,float)) else None
            rows.append({'Indicador':MATCH_DISPLAY_LABELS[canonical],'Casa':format_metric_value(canonical,home),'Fora':format_metric_value(canonical,away),'Total':format_metric_value(canonical,total)})
        st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
        st.caption('Cada indicador aparece uma única vez. Quando existem várias fontes para a mesma métrica, o sistema escolhe uma fonte prioritária e não soma fontes diferentes.')
    else:
        st.info('Sem estatísticas persistidas para esta partida. O sistema não inventa valores.')

    if m['status']=='SCHEDULED':
        analysis=build_pre_match_analysis(m);st.subheader('🔮 Análise pré-jogo');c1,c2,c3=st.columns(3);c1.metric('Casa',f'{analysis["probabilities"]["home"] or 0}%');c2.metric('Empate',f'{analysis["probabilities"]["draw"] or 0}%');c3.metric('Fora',f'{analysis["probabilities"]["away"] or 0}%');st.caption(f'Amostra histórica: {analysis["sample_home"]} casa / {analysis["sample_away"]} fora. Gols esperados: {analysis["xg_home"] if analysis["xg_home"] is not None else "sem dados"} × {analysis["xg_away"] if analysis["xg_away"] is not None else "sem dados"}.')

    players=get_players(selected);unique_players={x['id']:x for x in players}
    st.subheader(f'👥 Jogadores • {len(unique_players)}')
    if players:
        teams={}
        for p in players:teams.setdefault(p.get('team_id'),[]).append(p)
        team_order=[m['home_id'],m['away_id']]
        for tid in team_order+[x for x in teams if x not in team_order]:
            plist=teams.get(tid,[])
            if not plist:continue
            team_name=m['home_name'] if tid==m['home_id'] else m['away_name'] if tid==m['away_id'] else 'Equipe'
            st.markdown(f'#### {team_name}')
            for pid in sorted({p['id'] for p in plist},key=lambda x: next((p['name'] for p in plist if p['id']==x),'')):
                p0=next(p for p in plist if p['id']==pid)
                pstats=[p for p in plist if p['id']==pid]
                with st.expander(f'👤 {p0["name"]}  •  {position_label(p0.get("position"))}',expanded=False):
                    table=[]
                    for canonical in PLAYER_DISPLAY_ORDER:
                        candidates=[r for r in pstats if canonical_player_metric(r.get('metric'))==canonical]
                        chosen=choose_preferred_stat(candidates)
                        value=chosen.get('value') if chosen else None
                        table.append({'Indicador':PLAYER_DISPLAY_LABELS[canonical],'Valor':format_metric_value(canonical,value)})
                    st.dataframe(pd.DataFrame(table),hide_index=True,use_container_width=True)
    else:st.info('Nenhum dado individual persistido para esta partida.')

    if st.button('🧩 Enriquecer esta partida',key=f'e_{selected}',use_container_width=True):
        with st.spinner('Enriquecendo com fontes disponíveis...'):n=enrich([m])
        st.success(f'Enriquecimento concluído: {n} registros. Recarregue a partida para visualizar os dados atualizados.')

st.divider()
with st.expander('🩺 Diagnóstico do sistema'):
    u=usage_today('API-Football');st.caption(f'API-Football: {u.get("calls",0)} chamadas registradas hoje • proteção: 80/dia e 8/min • cache ativo.')
    ds=get_diagnostics(50)
    if not ds:st.info('Nenhum diagnóstico registrado ainda.')
    else:
        ddf=pd.DataFrame(ds)[['created_at','stage','source','status','message']].copy();ddf['status']=ddf['status'].map(diagnostic_status_label);st.dataframe(ddf,hide_index=True,use_container_width=True)
    st.caption('O diagnóstico diferencia chave ausente, erro de fonte, sucesso de coleta e sucesso de enriquecimento.')
with st.expander('⚙️ Enriquecimento em lote'):
    choices=[m for m in matches if m['status'] in ('FINISHED','LIVE','PAUSED')];labels={f'{m["home_name"]} × {m["away_name"]} • {manaos_time(m["start_time"])}':m for m in choices};picked=st.multiselect('Selecione até 5 partidas',list(labels),max_selections=5)
    if st.button('🚀 Enriquecer selecionadas',use_container_width=True):
        if not picked:st.warning('Selecione pelo menos uma partida.')
        else:
            with st.spinner('Enriquecendo até 5 partidas...'):n=enrich([labels[x] for x in picked])
            st.success(f'Operação concluída. {n} registros processados.')
with st.expander('🧹 Cache'):
    st.caption('O cache reduz consultas repetidas durante os testes. Limpar o cache pode consumir chamadas novamente, portanto faça isso somente quando quiser forçar uma atualização.')
    if st.button('Limpar cache de consultas',use_container_width=True):st.cache_data.clear();st.success('Cache limpo. Nenhuma API foi consultada automaticamente.')
