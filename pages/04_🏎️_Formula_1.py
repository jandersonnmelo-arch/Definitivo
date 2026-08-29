import pandas as pd
import streamlit as st
from core.f1 import season_races, races, future, completed, race_datetime, prediction

st.set_page_config(page_title='Arena 360 • Fórmula 1', page_icon='🏎️', layout='wide')
st.title('🏎️ Arena 360 • Fórmula 1')
st.caption('Calendário e dados oficiais · Jolpica F1 · temporada 2026')
st.info('Histórico usado nas projeções: últimas 5 corridas concluídas. Nenhum resultado futuro é tratado como fato.')

try:
    all_races = races(season_races())
except Exception as exc:
    st.error('Não foi possível carregar o calendário oficial da F1.')
    st.code(str(exc))
    st.stop()

if not all_races:
    st.warning('Nenhuma corrida foi retornada pela fonte oficial.')
    st.stop()

future_races = future(all_races)
completed_races = completed(all_races)

st.subheader('📅 Calendário F1')
calendar_rows=[]
for r in all_races:
    dt=race_datetime(r)
    calendar_rows.append({'Data':dt.strftime('%d/%m/%Y') if dt else '—','Evento':str(r.get('raceName','—')),'Circuito':str(r.get('Circuit',{}).get('circuitName','—')),'Horário':dt.strftime('%d/%m/%Y %H:%M UTC') if dt else '—','Status':'Futura' if r in future_races else 'Concluída'})
st.dataframe(pd.DataFrame(calendar_rows),use_container_width=True,hide_index=True)

options=future_races if future_races else all_races
race=st.selectbox('Corrida para analisar',options,index=0,format_func=lambda r:f"{r.get('date','—')} — {r.get('raceName','GP')}")
dt=race_datetime(race)
st.caption(f"{race.get('raceName','GP')} · {race.get('Circuit',{}).get('circuitName','—')} · {dt.strftime('%d/%m/%Y %H:%M UTC') if dt else 'horário não informado'}")

if st.button('🏎️ Analisar corrida',type='primary',use_container_width=True):
    try:
        with st.spinner('Consultando dados oficiais da temporada...'):
            preds=prediction(all_races)
        if not preds: raise RuntimeError('Não foi possível montar a previsão com os dados disponíveis.')
        top=preds[0]
        st.success('Análise concluída.')
        st.subheader('🎯 Probabilidade de vitória')
        c1,c2=st.columns(2); c1.metric(top['Piloto'],f"{top['Vitória %']:.1f}%"); c2.metric('Equipe favorita',top['Equipe'])
        st.progress(min(max(top['Vitória %']/100,0),1))
        st.subheader('📊 Pilotos — probabilidades')
        st.dataframe(pd.DataFrame([{'Piloto':x['Piloto'],'Equipe':x['Equipe'],'Vencedor':f"{x['Vitória %']:.1f}%",'Top 3/Pódio':f"{x['Top 3/Pódio %']:.1f}%",'Pontos esperados':f"{x['Pontos esperados']:.1f}"} for x in preds[:10]]),use_container_width=True,hide_index=True)
        st.subheader('📚 Base usada no cálculo')
        st.dataframe(pd.DataFrame([{'Piloto':x['Piloto'],'Equipe':x['Equipe'],'Pontos campeonato':x['Pontos'],'Vitórias':x['Vitórias'],'Média chegada (5)':f"{x['Média chegada (5)']:.1f}" if x['Média chegada (5)']<99 else '—','Voltas rápidas (5)':x['Voltas rápidas (5)']} for x in preds[:10]]),use_container_width=True,hide_index=True)
    except Exception as exc:
        st.error('A análise F1 falhou. Nenhum dado fictício foi usado.')
        st.code(str(exc))
