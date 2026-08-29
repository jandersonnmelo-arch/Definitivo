from datetime import date, timedelta
import pandas as pd
import streamlit as st
from core.nfl import NFL_TEAMS, team_schedule, summary, parse_team_stats, parse_players, team_averages, PROVIDER

st.set_page_config(page_title='Arena 360 • Futebol Americano',page_icon='🏈',layout='wide')
st.title('🏈 Arena 360 • Futebol Americano')
st.caption('NFL · calendário, histórico, médias e jogadores')
st.info('Calendário → seleção da partida → enriquecimento → estatísticas específicas do futebol americano → histórico.')

team=st.selectbox('Equipe',list(NFL_TEAMS.keys()))
code=NFL_TEAMS[team]

st.subheader('📅 Calendário')
c1,c2=st.columns(2)
start=c1.date_input('De',date.today(),key='nfl_start')
end=c2.date_input('Até',date.today()+timedelta(days=60),key='nfl_end')
if end<start:
    st.error('A data final não pode ser anterior à inicial.'); st.stop()

if st.button('🔄 Carregar calendário',use_container_width=True):
    try:
        with st.spinner('Consultando calendário NFL/API-Sports...'):
            games=team_schedule(code,start,end)
        if games:
            st.success(f'{len(games)} partida(s) encontrada(s). Horários em Manaus.')
            st.dataframe(pd.DataFrame(games),use_container_width=True,hide_index=True)
            st.session_state['nfl_games']=games
        else:
            st.info('Nenhuma partida encontrada para o período.')
    except Exception as exc:
        st.error(f'❌ Calendário NFL indisponível: {type(exc).__name__}: {exc}')

games=st.session_state.get('nfl_games',[])
if games:
    labels=[f"{g['Data']} {g['Hora (Manaus)']} — {g['Casa']} x {g['Fora']}" for g in games]
    idx=st.selectbox('🏈 Selecionar partida',range(len(games)),format_func=lambda i:labels[i])
    game=games[idx]
    if st.button('📊 Enriquecer partida',type='primary',use_container_width=True):
        try:
            with st.spinner('Carregando estatísticas da partida e jogadores...'):
                team_data,player_data,_raw_game=summary(game['game_id'])
                team_stats=parse_team_stats(team_data)
                players=parse_players(player_data)
            st.success('Partida enriquecida.')
            st.subheader('📈 Estatísticas das equipes')
            if team_stats:
                st.dataframe(pd.DataFrame(team_stats),use_container_width=True,hide_index=True)
            else:
                st.warning('A fonte não retornou estatísticas de equipe para esta partida.')
            st.subheader('👥 Jogadores')
            if players:
                names=sorted({str(x.get('Jogador','—')) for x in players},key=str.casefold)
                st.caption(f'{len(names)} jogador(es) encontrado(s).')
                for name in names:
                    pdata=[x for x in players if str(x.get('Jogador','—'))==name]
                    with st.expander(f'🏈 {name}',expanded=False):
                        st.dataframe(pd.DataFrame(pdata),use_container_width=True,hide_index=True)
            else:
                st.info('Nenhum dado individual retornado para a partida.')
        except Exception as exc:
            st.error(f'❌ Não foi possível enriquecer a partida: {type(exc).__name__}: {exc}')

st.divider()
st.subheader(f'📊 Médias recentes — {team}')
if st.button('📈 Calcular últimas 5 partidas',use_container_width=True):
    try:
        with st.spinner('Calculando histórico...'):
            recent,avg=team_averages(code,5)
        if recent:
            st.dataframe(pd.DataFrame(recent),use_container_width=True,hide_index=True)
        if avg:
            cols=st.columns(min(5,len(avg)))
            for i,(k,v) in enumerate(avg.items()):
                cols[i%len(cols)].metric(k,f'{v:.1f}')
        else:
            st.info('Não foi possível calcular médias com os dados disponíveis.')
    except Exception as exc:
        st.error(f'❌ Histórico NFL indisponível: {type(exc).__name__}: {exc}')

with st.expander('🧪 Diagnóstico',expanded=False):
    st.write(f'Fonte: {PROVIDER}. Base: v1.american-football.api-sports.io.')
    st.write('NFL = league 1. O calendário usa a temporada 2026 e filtra o intervalo escolhido. Horários são apresentados em America/Manaus.')
    st.write('Enriquecimento: /games/statistics/teams e /games/statistics/players. A API-NFL cobre estatísticas de passing, rushing, receiving, defensive, kicking, returns, fumbles e interceptações.')
    st.caption('A fonte informa 100 requisições/dia no plano gratuito; o módulo possui proteção própria para não consumir a quota durante testes.')
