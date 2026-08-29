from __future__ import annotations

import pandas as pd
import streamlit as st

from core.basketball.engine import BasketballSourceError, supported_competitions, collect_team_history
from core.basketball.nba import NBA_TEAMS
from core.basketball.nbb import TEAMS as NBB_TEAMS

st.set_page_config(page_title="Arena 360 • Basquete", page_icon="🏀", layout="wide")

st.title("🏀 Arena 360 • Basquete")
st.caption("Módulo isolado do Futebol • NBA e NBB")
st.info("Primeiro validamos as fontes e a cobertura. Os dados deste módulo ainda não entram no banco principal do Futebol.")

competition = st.selectbox("Competição", supported_competitions())
months = st.slider("Janela histórica", 3, 12, 8)

if competition == "NBA":
    teams = list(NBA_TEAMS)
else:
    teams = list(NBB_TEAMS)

team = st.selectbox("Equipe", teams)

if st.button("🔬 Testar histórico", type="primary", use_container_width=True):
    progress = st.progress(0, text=f"Consultando {competition}...")
    try:
        progress.progress(20, text="Carregando calendário/histórico...")
        result = collect_team_history(competition, team, months)
        progress.progress(100, text="Teste concluído.")

        games = pd.DataFrame(result.get("games") or [])
        players = pd.DataFrame(result.get("players") or [])
        errors = result.get("errors") or []

        st.success(f"{competition}: {len(games)} jogos reconstruídos • {len(players)} registros individuais.")

        st.subheader("📅 Histórico da equipe")
        if not games.empty:
            st.dataframe(games, use_container_width=True, hide_index=True)
        else:
            st.warning("Nenhum jogo foi reconstruído.")

        st.subheader("👥 Dados individuais")
        if not players.empty:
            st.dataframe(players, use_container_width=True, hide_index=True)
        else:
            st.warning("Nenhum dado individual foi reconstruído.")

        st.subheader("🧪 Diagnóstico")
        checks = {
            "Jogos": not games.empty,
            "Dados individuais": not players.empty,
        }
        if competition == "NBA" and not games.empty:
            checks.update({
                "Placar": {"PF", "PA"}.issubset(games.columns),
                "Q1": {"Q1_PF", "Q1_PA"}.issubset(games.columns),
                "Q2": {"Q2_PF", "Q2_PA"}.issubset(games.columns),
                "Q3": {"Q3_PF", "Q3_PA"}.issubset(games.columns),
                "Q4": {"Q4_PF", "Q4_PA"}.issubset(games.columns),
                "H1": {"H1_PF", "H1_PA"}.issubset(games.columns),
                "H2": {"H2_PF", "H2_PA"}.issubset(games.columns),
                "Rebotes": "REB" in games.columns,
                "Assistências": "AST" in games.columns,
                "Roubos": "STL" in games.columns,
                "Tocos": "BLK" in games.columns,
                "Turnovers": "TOV" in games.columns,
            })
        elif competition == "NBB" and not games.empty:
            checks.update({
                "Placar": {"PF", "PA"}.issubset(games.columns),
                "Resultado/jogo": {"home", "away", "played"}.issubset(games.columns),
            })

        st.dataframe(pd.DataFrame([{"Indicador": k, "Status": "✅" if v else "❌"} for k, v in checks.items()]), use_container_width=True, hide_index=True)

        if errors:
            st.warning(f"{len(errors)} registro(s) apresentaram erro.")
            st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)

        st.caption("Este teste não grava dados no banco principal. A promoção para persistência acontecerá somente depois da validação.")

    except BasketballSourceError as exc:
        progress.empty()
        st.error(str(exc))
    except Exception as exc:
        progress.empty()
        st.error(f"❌ Teste não concluído: {type(exc).__name__}: {exc}")
