import streamlit as st
import pandas as pd

from core.ai_dataset import build_dataset_v1, dataset_summary, load_dataset

st.set_page_config(page_title='Arena 360 • IA', page_icon='🤖', layout='centered')

st.title('🤖 Banco de dados da IA')
st.caption('Dataset IA v1 • somente dados persistidos • corte temporal para evitar vazamento de resultado')

summary = dataset_summary()
c1, c2, c3, c4 = st.columns(4)
c1.metric('Amostras', summary['total'])
c2.metric('Prontas', summary['training_ready'])
c3.metric('Treino', summary['train'])
c4.metric('Teste', summary['test'])

st.info('Divisão cronológica: 70% treino • 15% validação • 15% teste. A partida nunca entra no conjunto de características usando o próprio resultado.')

if st.button('🧠 Construir / atualizar Dataset IA v1', use_container_width=True, type='primary'):
    with st.spinner('Construindo dataset cronológico a partir do banco histórico...'):
        result = build_dataset_v1()
    st.success(f"Dataset atualizado: {result['training_ready']} amostras prontas para treinamento.")
    st.rerun()

st.markdown('### 🎯 Alvos da IA')
st.write('• Resultado: Casa / Empate / Fora')
st.write('• Over 2.5 gols')
st.write('• Ambas marcam')
st.write('• Gols da equipe da casa')
st.write('• Gols da equipe visitante')

st.markdown('### 📊 Amostra do dataset')
rows = load_dataset(training_ready=True)
if rows:
    preview = []
    for r in rows[-20:]:
        f = r.get('features', {})
        preview.append({
            'Data corte': r.get('cutoff_time'),
            'Casa': r.get('home_team_name'),
            'Fora': r.get('away_team_name'),
            'Divisão': r.get('split'),
            'Qualidade': r.get('quality_score'),
            'Gols casa': r.get('target_home_goals'),
            'Gols fora': r.get('target_away_goals'),
            'Resultado': r.get('target_result'),
            'Over 2.5': 'SIM' if r.get('target_over_25') else 'NÃO',
            'BTTS': 'SIM' if r.get('target_btts') else 'NÃO',
            'xG casa': f.get('xg_home'),
            'xG fora': f.get('xg_away'),
        })
    st.dataframe(pd.DataFrame(preview), hide_index=True, use_container_width=True)
else:
    st.warning('Ainda não existem amostras prontas. Primeiro é necessário ter partidas finalizadas com histórico persistido.')

st.markdown('### 🔒 Regras de qualidade')
st.write('• Não inventar estatísticas ausentes.')
st.write('• Usar somente partidas anteriores ao horário da partida-alvo.')
st.write('• Exigir pelo menos 5 jogos históricos por equipe para marcar a amostra como pronta.')
st.write('• Separar treino, validação e teste por ordem cronológica, nunca aleatoriamente.')
st.write('• Guardar o resultado real somente como alvo.')
