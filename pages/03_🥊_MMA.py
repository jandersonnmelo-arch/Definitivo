import pandas as pd
import requests
import streamlit as st
from datetime import date, timedelta

from core.mma import MMA_LUTAS, VERSION, career_table, pct, technical_table, strike_table
from core.mma_calendar import upcoming_fights, selected_fight_analysis

st.set_page_config(page_title="Arena 360 • MMA", page_icon="🥊", layout="centered", initial_sidebar_state="expanded")

st.markdown("""
<style>
.stApp{background:#060918}.block-container{max-width:760px;padding-top:1rem;padding-bottom:4rem}
.brand{display:flex;gap:12px;align-items:center;margin-bottom:20px}.mark{width:46px;height:46px;border-radius:14px;background:#b7ff27;color:#081000;display:grid;place-items:center;font-size:25px}
.eyebrow{font-size:11px;letter-spacing:2px;color:#b7ff27;font-weight:800}.brandname{font-size:21px;font-weight:850}.hero{font-size:31px;font-weight:850;line-height:1.08;margin:18px 0 10px}.hero span{color:#b7ff27}.small{font-size:12px;color:#858da7}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="brand"><div class="mark">🥊</div><div><div class="eyebrow">ARENA 360</div><div class="brandname">MMA</div></div></div>', unsafe_allow_html=True)
st.markdown('<div class="hero">Calendário e análise <span>de lutas.</span></div>', unsafe_allow_html=True)
st.caption("Fonte oficial UFC → calendário → luta selecionada → dois lutadores → últimas 5 lutas → estatísticas → IA.")

st.subheader("📅 Próximas lutas — 2 meses")
st.caption("A janela usa os próximos 60 dias. As datas vêm dos eventos oficiais retornados pela UFC JSON:API.")

if st.button("🔄 Atualizar calendário", type="primary", use_container_width=True):
    st.cache_data.clear()
    st.session_state.pop("mma_fight", None)
    st.rerun()

try:
    fights = upcoming_fights(days=60)
except requests.HTTPError as exc:
    st.error("A UFC JSON:API rejeitou a consulta do calendário.")
    response = exc.response
    if response is not None:
        st.code(f"HTTP {response.status_code}\nURL: {response.url}\nResposta: {response.text[:1000]}")
    st.stop()
except Exception as exc:
    st.error("Não foi possível carregar o calendário oficial da UFC agora.")
    st.code(str(exc))
    st.stop()

if not fights:
    st.warning("Nenhuma luta foi retornada pela UFC para os próximos 2 meses.")
    st.stop()

# Agrupa por evento/data e mantém a tela compacta.
by_event = {}
for fight in fights:
    by_event.setdefault((fight["event_date"], fight["event_name"]), []).append(fight)

fight_options = {}
for (event_date, event_name), event_fights in sorted(by_event.items()):
    event_fights = sorted(event_fights, key=lambda x: x["red_name"])
    label = f"📅 {event_date} • {event_name} • {len(event_fights)} luta(s)"
    with st.expander(label, expanded=False):
        for fight in event_fights:
            option = f"🥊 {fight['red_name']} × {fight['blue_name']}"
            if fight.get("weight_class") and fight["weight_class"] != "—":
                option += f" • {fight['weight_class']}"
            fight_options[option] = fight
            if st.button(option, key=f"fight_{fight.get('fight_id') or option}", use_container_width=True):
                st.session_state["mma_fight"] = fight
                st.rerun()

st.caption(f"{len(fights)} luta(s) encontradas no período. Selecione uma luta para carregar automaticamente os dois lutadores.")

selected = st.session_state.get("mma_fight")
if not selected:
    st.info("👆 Selecione uma luta no calendário acima. O app buscará automaticamente o histórico dos dois atletas.")
    st.stop()

st.divider()
st.subheader(f"🥊 {selected['red_name']} × {selected['blue_name']}")
st.caption(f"{selected['event_name']} • {selected['event_date']} • {selected.get('weight_class', '—')}")

if st.button("🔎 Buscar dados dos dois lutadores", type="primary", use_container_width=True):
    with st.status("Buscando perfil e últimas 5 lutas dos dois atletas...", expanded=True) as status:
        try:
            analysis = selected_fight_analysis(selected)
            st.session_state["mma_fight_analysis"] = analysis
            status.update(label="Dados dos dois lutadores carregados.", state="complete")
        except requests.HTTPError as exc:
            status.update(label="Consulta UFC falhou.", state="error")
            response = exc.response
            st.error("A UFC JSON:API rejeitou a consulta.")
            if response is not None:
                st.code(f"HTTP {response.status_code}\nURL: {response.url}\nResposta: {response.text[:1000]}")
        except Exception as exc:
            status.update(label="Coleta falhou.", state="error")
            st.error("A coleta oficial falhou. Nenhum dado fictício foi usado.")
            st.code(str(exc))

analysis = st.session_state.get("mma_fight_analysis")
if not analysis:
    st.stop()

fighters = analysis.get("fighters", [])
if len(fighters) < 2:
    st.warning("A UFC não retornou os dois perfis necessários para esta luta.")
    for item in fighters:
        if item.get("error"):
            st.caption(f"{item.get('name')}: {item['error']}")
    st.stop()

cols = st.columns(2)
for col, fighter in zip(cols, fighters):
    with col:
        st.markdown(f"### 🥊 {fighter['name']}")
        hist = fighter.get("history", [])
        wins = fighter.get("wins_last5", 0)
        losses = fighter.get("losses_last5", 0)
        col1, col2 = st.columns(2)
        col1.metric("Vitórias (5)", wins)
        col2.metric("Derrotas (5)", losses)
        st.metric("Aproveitamento", pct(fighter.get("win_rate_last5")))
        avg_round = fighter.get("avg_round_last5")
        st.metric("Média do round", f"{avg_round:.2f}" if avg_round is not None else "—")

        profile = fighter.get("profile") or {}
        attrs = profile.get("attrs", {})
        st.dataframe(pd.DataFrame([{
            "Apelido": attrs.get("nickname", "—"),
            "Altura": attrs.get("stats_height", "—"),
            "Peso": attrs.get("stats_weight", "—"),
            "Envergadura": attrs.get("stats_reach_arm", "—"),
            "Estreia": attrs.get("octagon_debut", "—"),
        }]), use_container_width=True, hide_index=True)

        with st.expander(f"📅 Últimas {MMA_LUTAS} lutas — {fighter['name']}", expanded=True):
            st.dataframe(pd.DataFrame(hist), use_container_width=True, hide_index=True)

        stat = profile.get("stat", {})
        with st.expander("📊 Estatísticas técnicas de carreira", expanded=False):
            st.dataframe(technical_table(stat), use_container_width=True, hide_index=True)
        with st.expander("🎯 Distribuição dos golpes", expanded=False):
            st.dataframe(strike_table(stat), use_container_width=True, hide_index=True)
        with st.expander("🏆 Registro de carreira", expanded=False):
            st.dataframe(career_table(stat), use_container_width=True, hide_index=True)

st.success("Fluxo MMA restaurado: calendário de 2 meses → luta selecionada → dados dos dois lutadores → últimas 5 lutas de cada atleta.")
st.info("As estatísticas técnicas são de carreira; a forma recente usa somente as 5 últimas lutas oficiais disponíveis.")
