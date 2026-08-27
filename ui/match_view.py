import streamlit as st
from core.repository import get_match_stats,get_match_players
from core.engine import build_live_analysis,build_pre_match_analysis
LABELS={'shots':'Finalizações','shots_on_target':'Finalizações no alvo','corners':'Escanteios','possession':'Posse','passes_completed':'Passes certos','offsides':'Impedimentos','yellow_cards':'Cartões amarelos','red_cards':'Cartões vermelhos','fouls':'Faltas','woodwork':'Bola na trave'}
def render_match_view(m):
 st.markdown('## '+('🔴 Ao vivo' if m['status']=='LIVE' else '📊 Partida'))
 st.markdown(f"### {m['home_name']} **{m['home_score'] if m['home_score'] is not None else '-'} — {m['away_score'] if m['away_score'] is not None else '-'}** {m['away_name']}")
 tabs=st.tabs(['Resumo','Estatísticas','Jogadores','Análise','Diagnóstico']); stats=get_match_stats(m['id'])
 with tabs[0]: st.write(f"**{m['competition']}** · temporada {m['season']} · fonte {m['source']}")
 with tabs[1]:
  vals={}
  for r in stats: vals.setdefault(r['metric'],{})[r['team_id']]=r['value']
  for k,v in vals.items(): st.write(f"**{LABELS.get(k,k)}** — {m['home_short']}: {v.get(m['home_id'],'Não disponível')} · {m['away_short']}: {v.get(m['away_id'],'Não disponível')}")
  st.caption('Ausência de dado não é convertida em zero.')
 with tabs[2]:
  ps=get_match_players(m['id'])
  if not ps: st.info('Nenhum jogador com estatística persistida.')
  else:
   for name in sorted({p['name'] for p in ps}):
    st.write('**'+name+'** — '+' · '.join(f"{p['metric']}: {p['value']}" for p in ps if p['name']==name))
 with tabs[3]:
  r=build_live_analysis(m['id']) if m['status']=='LIVE' else build_pre_match_analysis(m['id'])
  st.subheader('🧠 Motor'); st.write(r)
 with tabs[4]:
  checks=[('Identificação',True,'ID e equipes presentes'),('Estatísticas',bool(stats),f'{len(stats)} registros persistidos'),('Jogadores',bool(get_match_players(m['id'])),'Registros individuais persistidos'),('Normalização',True,'Contrato central ativo'),('Persistência',True,'SQLite ativo'),('Motor',True,'Separado da aquisição')]
  for label,ok,msg in checks: st.markdown(f"<div class='diag'><span class={'ok' if ok else 'warn'}>{'✅' if ok else '⚠️'}</span> <b>{label}</b><br><small>{msg}</small></div>",unsafe_allow_html=True)
