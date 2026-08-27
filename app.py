import streamlit as st
from core.db import init_db, seed_demo
from core.repository import get_dashboard_matches, get_match
from core.engine import build_live_analysis, build_pre_match_analysis
from ui.theme import inject_css
from ui.cards import render_match_card, render_featured
from ui.match_view import render_match_view

st.set_page_config(page_title="Arena 360 Analytics", page_icon="🏟️", layout="centered", initial_sidebar_state="collapsed")
inject_css()
init_db()
seed_demo()

if "page" not in st.session_state: st.session_state.page = "home"
if "selected_match" not in st.session_state: st.session_state.selected_match = None

def open_match(match_id):
    st.session_state.page = "match"
    st.session_state.selected_match = match_id

st.markdown('<div class="top-brand"><div class="brand-mark">🏟️</div><div><div class="eyebrow">PLACAR</div><div class="brand-name">Arena 360</div></div></div>', unsafe_allow_html=True)

if st.session_state.page == "match":
    if st.button("← Voltar"): st.session_state.page = "home"
    match = get_match(st.session_state.selected_match)
    if match: render_match_view(match)
    st.stop()

st.markdown('<div class="hero-title">Toda a emoção, <span>em um só lugar.</span></div>', unsafe_allow_html=True)
sport = st.segmented_control("Esporte", ["Todos", "⚽ Futebol", "🏀 Basquete", "🏐 Vôlei"], default="⚽ Futebol", label_visibility="collapsed")
matches = get_dashboard_matches(sport)
live = [m for m in matches if m["status"] == "LIVE"]
if live:
    st.markdown('<div class="section-label">🔴 Destaque agora</div>', unsafe_allow_html=True)
    render_featured(live[0], open_match)
st.markdown(f'<div class="section-row"><span>⚽ Partidas</span><small>{len(matches)} eventos</small></div>', unsafe_allow_html=True)
for m in matches: render_match_card(m, open_match)
