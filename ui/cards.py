import streamlit as st
def _time(m): return f"{m['minute']}'" if m['status']=='LIVE' else (m['start_time'][11:16] if m['status']=='SCHEDULED' else 'FT')
def render_match_card(m,on_click):
 st.markdown(f"<div class='match-card'><div class='meta'><span class='pill'>{m['competition']}</span> · {_time(m)}</div><div class='teams'><div class='team'>{m['home_short']}<br><small>{m['home_name']}</small></div><div class='score'>{m['home_score'] if m['home_score'] is not None else ''} — {m['away_score'] if m['away_score'] is not None else ''}</div><div class='team'>{m['away_short']}<br><small>{m['away_name']}</small></div></div></div>",unsafe_allow_html=True)
 if st.button('Abrir partida',key=f"open_{m['id']}",use_container_width=True): on_click(m['id'])
def render_featured(m,on_click):
 st.markdown(f"<div class='featured'><span class='live-badge'>🔴 AO VIVO</span><div class='teams'><div class='team'>{m['home_short']}<br><small>{m['home_name']}</small></div><div class='score'>{m['home_score']} : {m['away_score']}</div><div class='team'>{m['away_short']}<br><small>{m['away_name']}</small></div></div></div>",unsafe_allow_html=True)
 if st.button('Ver partida ao vivo',key=f"featured_{m['id']}",use_container_width=True): on_click(m['id'])
