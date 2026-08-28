import streamlit as st
import pandas as pd

from core.ai_dataset import build_dataset_v1, dataset_summary, load_dataset
from core.ai_validation import validate_ai_data, build_and_validate_ai_dataset

st.set_page_config(page_title='Arena 360 • IA', page_icon='🤖', layout='centered')
st.title('🤖 Banco de dados da IA')
st.caption('Dataset IA v1 • dados persistidos • validação de qualidade • corte temporal contra vazamento')

summary = dataset_summary()
c1,c2,c3,c4 = st.columns(4)
c1.metric('Amostras',summary['total']); c2.metric('Prontas',summary['training_ready']); c3.metric('Treino',summary['train']); c4.metric('Teste',summary['test'])
st.info('Divisão cronológica: 70% treino • 15% validação • 15% teste. A partida-alvo nunca fornece o próprio resultado às características.')

st.markdown('### 🔎 Validação da base')
st.caption('Antes do treinamento, o sistema verifica duplicidades, vínculos de equipes, registros órfãos, alvos e corte temporal.')

b1,b2 = st.columns(2)
with b1:
    if st.button('🧪 Validar base atual',use_container_width=True):
        with st.spinner('Validando banco histórico e Dataset IA...'): result=validate_ai_data()
        st.session_state['ai_validation']=result
with b2:
    if st.button('🧠 Construir + validar Dataset',use_container_width=True,type='primary'):
        with st.spinner('Construindo Dataset IA v1 e validando a base...'): result=build_and_validate_ai_dataset()
        st.session_state['ai_validation']=result
        st.rerun()

validation=st.session_state.get('ai_validation')
if validation:
    source=validation['source']; ds=validation['dataset']
    if validation['ok']: st.success('🟢 Base aprovada para a próxima etapa da IA.')
    else: st.warning(f"🟡 Validação encontrou {len(validation['issues'])} ponto(s) para revisar antes do treinamento.")
    q1,q2,q3,q4=st.columns(4)
    q1.metric('Jogos finalizados',source['finished_matches'])
    q2.metric('Duplicidades',source['duplicate_matches'])
    q3.metric('Stats órfãs',source['orphan_stats'])
    q4.metric('Stats jogadores',source['player_stats_total'])
    q5,q6,q7,q8=st.columns(4)
    q5.metric('Dataset',ds['dataset_rows'])
    q6.metric('Corte temporal',ds['cutoff_violations'])
    q7.metric('Targets inválidos',ds['invalid_targets'])
    q8.metric('Qualidade < 0,50',ds['low_quality'])
    st.caption(f"Verificador {validation['validator_version']} • executado em {validation['checked_at']}")
    if validation['issues']:
        st.markdown('#### ⚠️ Pontos encontrados')
        st.dataframe(pd.DataFrame([{'Tipo':x[0],'Onde':x[1],'Detalhe':x[2]} for x in validation['issues']]),hide_index=True,use_container_width=True)
    else:
        st.success(f"Sem inconsistências detectadas. {source['players_total']} jogadores e {source['stats_total']} estatísticas de equipe estão persistidos.")

st.markdown('### 🎯 Alvos da IA')
st.write('• Resultado: Casa / Empate / Fora')
st.write('• Over 2.5 gols')
st.write('• Ambas marcam')
st.write('• Gols da equipe da casa')
st.write('• Gols da equipe visitante')

st.markdown('### 📊 Amostra do dataset')
rows=load_dataset(training_ready=True)
if rows:
    preview=[]
    for r in rows[-20:]:
        f=r.get('features',{})
        preview.append({'Data corte':r.get('cutoff_time'),'Casa':r.get('home_team_name'),'Fora':r.get('away_team_name'),'Divisão':r.get('split'),'Qualidade':r.get('quality_score'),'Gols casa':r.get('target_home_goals'),'Gols fora':r.get('target_away_goals'),'Resultado':r.get('target_result'),'Over 2.5':'SIM' if r.get('target_over_25') else 'NÃO','BTTS':'SIM' if r.get('target_btts') else 'NÃO','xG casa':f.get('xg_home'),'xG fora':f.get('xg_away')})
    st.dataframe(pd.DataFrame(preview),hide_index=True,use_container_width=True)
else:
    st.warning('Ainda não existem amostras prontas. Primeiro é necessário ter partidas finalizadas com histórico persistido.')

st.markdown('### 🔒 Regras de qualidade')
st.write('• Não inventar estatísticas ausentes.')
st.write('• Usar somente partidas anteriores ao horário da partida-alvo.')
st.write('• Exigir pelo menos 5 jogos históricos por equipe para marcar a amostra como pronta.')
st.write('• Separar treino, validação e teste por ordem cronológica, nunca aleatoriamente.')
st.write('• Guardar o resultado real somente como alvo.')
