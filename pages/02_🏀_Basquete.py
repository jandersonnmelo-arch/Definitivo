from __future__ import annotations

import pandas as pd
import streamlit as st

from core.basketball.engine import BasketballSourceError, supported_competitions, collect_team_history
from core.basketball.nba import NBA_TEAMS
from core.basketball.nbb import TEAMS as NBB_TEAMS

st.set_page_config(page_title="Arena 360 • Basquete", page_icon="🏀", layout="wide")

st.title("🏀 Arena 360 • Basquete")
st.caption("Módulo isolado do Futebol • NBA e NBB")
st.info("Selecione uma competição e uma equipe para visualizar somente os dados e médias dessa equipe.")

competition = st.selectbox("Competição", supported_competitions())
months = st.slider("Janela histórica", 3, 12, 8)
teams = list(NBA_TEAMS) if competition == "NBA" else list(NBB_TEAMS)
team = st.selectbox("Equipe", teams)


def _numeric_mean(df: pd.DataFrame, column: str):
    if column not in df.columns:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def _fmt(value, decimals: int = 1):
    return "—" if value is None else f"{value:.{decimals}f}"


def render_team_summary(games: pd.DataFrame, competition_name: str):
    st.subheader(f"📊 Resumo da equipe — {team}")
    played = games[games["played"] == True].copy() if "played" in games.columns else games.copy()

    cols = st.columns(4)
    cols[0].metric("Jogos analisados", len(played))
    cols[1].metric("Média pontos feitos", _fmt(_numeric_mean(played, "PF")))
    cols[2].metric("Média pontos sofridos", _fmt(_numeric_mean(played, "PA")))
    if not played.empty and {"PF", "PA"}.issubset(played.columns):
        saldo = pd.to_numeric(played["PF"], errors="coerce") - pd.to_numeric(played["PA"], errors="coerce")
        cols[3].metric("Saldo médio", _fmt(float(saldo.mean()) if not saldo.dropna().empty else None))
    else:
        cols[3].metric("Saldo médio", "—")

    metric_groups = [
        ("🎯 Arremessos", [("FGM", "FG convertidos"), ("FGA", "FG tentados")]),
        ("3️⃣ Três pontos", [("3PM", "3PT convertidos"), ("3PA", "3PT tentados")]),
        ("🏀 Lance livre", [("FTM", "FT convertidos"), ("FTA", "FT tentados")]),
        ("📈 Jogo", [("REB", "Rebotes"), ("AST", "Assistências"), ("STL", "Roubos"), ("BLK", "Tocos"), ("TOV", "Turnovers")]),
    ]
    for title, metrics in metric_groups:
        available = [(column, label) for column, label in metrics if column in played.columns]
        if not available:
            continue
        with st.expander(title, expanded=True):
            metric_cols = st.columns(min(5, len(available)))
            for i, (column, label) in enumerate(available):
                metric_cols[i % len(metric_cols)].metric(label, _fmt(_numeric_mean(played, column)))

    if competition_name == "NBA":
        period_metrics = []
        for q in range(1, 5):
            period_metrics.extend([(f"Q{q}_PF", f"Q{q} feitos"), (f"Q{q}_PA", f"Q{q} sofridos"), (f"Q{q}_SALDO", f"Q{q} saldo")])
        period_metrics.extend([(f"H1_PF", "H1 feitos"), (f"H1_PA", "H1 sofridos"), (f"H1_SALDO", "H1 saldo"), (f"H2_PF", "H2 feitos"), (f"H2_PA", "H2 sofridos"), (f"H2_SALDO", "H2 saldo")])
        available = [(c, label) for c, label in period_metrics if c in played.columns]
        if available:
            with st.expander("⏱️ Períodos — quartos e metades", expanded=False):
                for start in range(0, len(available), 3):
                    row = available[start:start + 3]
                    c = st.columns(len(row))
                    for i, (column, label) in enumerate(row):
                        c[i].metric(label, _fmt(_numeric_mean(played, column)))


def render_nba_player(name: str, pdata: pd.DataFrame):
    labels = {
        "MIN": "Minutos", "PTS": "Pontos", "2PM": "2PT convertidos", "2PA": "2PT tentados",
        "3PM": "3PT convertidos", "3PA": "3PT tentados", "FTM": "FT convertidos", "FTA": "FT tentados",
        "REB": "Rebotes", "AST": "Assistências", "STL": "Roubos", "BLK": "Tocos", "TOV": "Turnovers",
    }
    with st.expander(f"🏀 {name}", expanded=False):
        st.caption(f"{len(pdata)} partida(s) com registro individual")
        available = [(c, label) for c, label in labels.items() if c in pdata.columns]
        for start in range(0, len(available), 4):
            row = available[start:start + 4]
            cols = st.columns(len(row))
            for i, (column, label) in enumerate(row):
                cols[i].metric(f"Média {label}", _fmt(_numeric_mean(pdata, column)))

        raw_cols = [c for c in ["Data", "game_id", "MIN", "PTS", "2PM", "2PA", "3PM", "3PA", "FTM", "FTA", "REB", "AST", "STL", "BLK", "TOV"] if c in pdata.columns]
        if raw_cols:
            st.dataframe(pdata[raw_cols], use_container_width=True, hide_index=True)


def render_nbb_player(name: str, pdata: pd.DataFrame):
    with st.expander(f"🏀 {name}", expanded=False):
        st.caption(f"{len(pdata)} registro(s) individual(is) encontrado(s) para o atleta")

        # A LNB entrega médias por categoria em tabelas diferentes. Mostramos
        # cada categoria separadamente, preservando os nomes/valores da fonte.
        category_col = "categoria" if "categoria" in pdata.columns else None
        if category_col:
            for category, cat_df in pdata.groupby(category_col, dropna=False):
                st.markdown(f"**{str(category).replace('-', ' ').title()}**")
                display = cat_df.drop(columns=[category_col], errors="ignore").copy()
                display = display.drop(columns=["competition", "Equipe", "Jogador"], errors="ignore")
                st.dataframe(display, use_container_width=True, hide_index=True)
        else:
            st.dataframe(pdata, use_container_width=True, hide_index=True)


def render_players(players: pd.DataFrame, competition_name: str):
    st.subheader(f"👥 Jogadores — {team}")
    if players.empty:
        st.warning("Nenhum dado individual foi reconstruído para esta equipe.")
        return

    player_col = "Jogador" if "Jogador" in players.columns else "player" if "player" in players.columns else None
    if player_col is None:
        st.warning("A fonte retornou registros individuais, mas não informou a coluna do jogador.")
        st.dataframe(players, use_container_width=True, hide_index=True)
        return

    names = sorted([str(x) for x in players[player_col].dropna().unique()], key=str.casefold)
    st.caption(f"{len(names)} jogador(es) encontrado(s). Abra somente o atleta que deseja consultar.")

    for name in names:
        pdata = players[players[player_col].astype(str) == name].copy()
        if competition_name == "NBA":
            render_nba_player(name, pdata)
        else:
            render_nbb_player(name, pdata)


if st.button("🔬 Testar histórico", type="primary", use_container_width=True):
    progress = st.progress(0, text=f"Consultando {competition} • {team}...")
    try:
        progress.progress(20, text="Carregando calendário/histórico...")
        result = collect_team_history(competition, team, months)
        progress.progress(100, text="Teste concluído.")

        games = pd.DataFrame(result.get("games") or [])
        players = pd.DataFrame(result.get("players") or [])
        errors = result.get("errors") or []

        st.success(f"{competition} • {team}: {len(games)} jogos reconstruídos • {len(players)} registros individuais.")

        if not games.empty:
            render_team_summary(games, competition)
            with st.expander(f"📅 Histórico de jogos — {team}", expanded=False):
                st.dataframe(games, use_container_width=True, hide_index=True)
        else:
            st.warning("Nenhum jogo foi reconstruído para a equipe selecionada.")

        render_players(players, competition)

        with st.expander("🧪 Diagnóstico", expanded=False):
            checks = {"Jogos": not games.empty, "Dados individuais": not players.empty}
            if competition == "NBA" and not games.empty:
                checks.update({
                    "Placar": {"PF", "PA"}.issubset(games.columns),
                    "Q1": {"Q1_PF", "Q1_PA"}.issubset(games.columns),
                    "Q2": {"Q2_PF", "Q2_PA"}.issubset(games.columns),
                    "Q3": {"Q3_PF", "Q3_PA"}.issubset(games.columns),
                    "Q4": {"Q4_PF", "Q4_PA"}.issubset(games.columns),
                    "H1": {"H1_PF", "H1_PA"}.issubset(games.columns),
                    "H2": {"H2_PF", "H2_PA"}.issubset(games.columns),
                    "Rebotes": "REB" in games.columns, "Assistências": "AST" in games.columns,
                    "Roubos": "STL" in games.columns, "Tocos": "BLK" in games.columns, "Turnovers": "TOV" in games.columns,
                })
            elif competition == "NBB" and not games.empty:
                checks.update({"Placar": {"PF", "PA"}.issubset(games.columns), "Resultado/jogo": {"home", "away", "played"}.issubset(games.columns)})
            st.dataframe(pd.DataFrame([{"Indicador": k, "Status": "✅" if v else "❌"} for k, v in checks.items()]), use_container_width=True, hide_index=True)

        if errors:
            with st.expander(f"⚠️ Erros ({len(errors)})", expanded=False):
                st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)

        st.caption("Os dados continuam sendo consultados pela mesma fonte; a interface agora organiza as informações por equipe e jogador.")

    except BasketballSourceError as exc:
        progress.empty()
        st.error(str(exc))
    except Exception as exc:
        progress.empty()
        st.error(f"❌ Teste não concluído: {type(exc).__name__}: {exc}")
