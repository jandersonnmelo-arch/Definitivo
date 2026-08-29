import pandas as pd
import requests
import streamlit as st

from core.mma import (
    MMA_LUTAS,
    VERSION,
    career_table,
    coverage,
    fighter_profile,
    history,
    pct,
    search_fighters,
    strike_table,
    technical_table,
)

st.set_page_config(page_title="Arena 360 • MMA", page_icon="🥊", layout="centered", initial_sidebar_state="expanded")

st.markdown("""
<style>
.stApp{background:#060918}.block-container{max-width:760px;padding-top:1rem;padding-bottom:4rem}
.brand{display:flex;gap:12px;align-items:center;margin-bottom:20px}.mark{width:46px;height:46px;border-radius:14px;background:#b7ff27;color:#081000;display:grid;place-items:center;font-size:25px}
.eyebrow{font-size:11px;letter-spacing:2px;color:#b7ff27;font-weight:800}.brandname{font-size:21px;font-weight:850}.hero{font-size:31px;font-weight:850;line-height:1.08;margin:18px 0 10px}.hero span{color:#b7ff27}.small{font-size:12px;color:#858da7}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="brand"><div class="mark">🥊</div><div><div class="eyebrow">ARENA 360</div><div class="brandname">MMA</div></div></div>', unsafe_allow_html=True)
st.markdown('<div class="hero">Análise MMA <span>com histórico real.</span></div>', unsafe_allow_html=True)
st.caption("Fonte oficial UFC → perfil → últimas 5 lutas → estatísticas → base para análise/IA.")
st.info("Regra oficial do módulo: o histórico é construído pelas exatamente 5 últimas lutas oficiais disponíveis. Não existe janela fixa de meses e nenhum resultado é inventado.")

search_text = st.text_input("Buscar lutador", "Alex Pereira")
try:
    matches = search_fighters(search_text.strip()) if search_text.strip() else []
except Exception as exc:
    st.error("Não foi possível consultar a API oficial do UFC agora.")
    st.caption("Nenhum dado fictício será exibido como se fosse real.")
    st.code(str(exc))
    st.stop()

if not matches:
    st.warning("Nenhum lutador encontrado. Tente outro nome.")
    st.stop()

selected_name = st.selectbox("Lutador", [x["name"] for x in matches])
st.caption(f"Histórico: exatamente {MMA_LUTAS} últimas lutas oficiais disponíveis.")

if st.button("🥊 Carregar histórico e estatísticas", type="primary", use_container_width=True):
    with st.status("Reconstruindo histórico oficial do UFC...", expanded=True) as status:
        try:
            profile = fighter_profile(selected_name)
            if not profile:
                raise RuntimeError("O UFC não retornou o perfil do lutador selecionado.")
            rows = history(profile)
            if len(rows) < MMA_LUTAS:
                raise RuntimeError("A API oficial respondeu, mas não foi possível localizar as 5 últimas lutas oficiais do atleta.")
            st.session_state["mma"] = {"profile": profile, "rows": rows, "name": selected_name}
            st.write("Lutas encontradas: 5 de 5")
            status.update(label="MMA carregado com sucesso.", state="complete")
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

lab = st.session_state.get("mma")
if lab:
    profile = lab["profile"]
    rows = lab["rows"]
    attrs = profile["attrs"]
    stat = profile["stat"]
    wins = sum(1 for x in rows if x["Resultado"] == "V")
    losses = sum(1 for x in rows if x["Resultado"] == "D")
    known = wins + losses

    st.success("UFC respondeu: perfil técnico + 5 das 5 lutas solicitadas.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Lutas", len(rows))
    c2.metric("Solicitadas", MMA_LUTAS)
    c3.metric("Vitórias", wins)
    c4.metric("Aproveitamento", pct(100 * wins / known if known else None))

    st.subheader("👤 Perfil do lutador")
    st.dataframe(pd.DataFrame([{
        "Nome": profile["name"],
        "Apelido": attrs.get("nickname", "—"),
        "Altura": attrs.get("stats_height", "—"),
        "Peso": attrs.get("stats_weight", "—"),
        "Envergadura": attrs.get("stats_reach_arm", "—"),
        "Estreia": attrs.get("octagon_debut", "—"),
    }]), use_container_width=True, hide_index=True)

    st.subheader("📅 Últimas 5 lutas")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.subheader("📊 Estatísticas técnicas de carreira")
    st.dataframe(technical_table(stat), use_container_width=True, hide_index=True)

    st.subheader("🎯 Distribuição dos golpes")
    st.dataframe(strike_table(stat), use_container_width=True, hide_index=True)

    st.subheader("🏆 Registro de carreira")
    st.dataframe(career_table(stat), use_container_width=True, hide_index=True)

    st.subheader("🧪 Diagnóstico de cobertura")
    st.dataframe(coverage(rows, profile, MMA_LUTAS), use_container_width=True, hide_index=True)
    st.info("As estatísticas técnicas do UFC são de carreira. O histórico de forma usa somente as últimas 5 lutas oficiais disponíveis.")
