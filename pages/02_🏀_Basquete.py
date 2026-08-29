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
            period_metrics.extend([(f"Q{q}_PF", f"Q{q} pontos feitos"), (f"Q{q}_PA", f"Q{q} pontos sofridos"), (f"Q{q}_SALDO", f"Q{q} saldo")])
        period_metrics.extend([
            ("H1_PF", "H1 pontos feitos"), ("H1_PA", "H1 pontos sofridos"), ("H1_SALDO", "H1 saldo"),
            ("H2_PF", "H2 pontos feitos"), ("H2_PA", "H2 pontos sofridos"), ("H2_SALDO", "H2 saldo"),
        ])
        available = [(c, label) for c, label in period_metrics if c in played.columns]
        if available:
            with st.expander("⏱️ Períodos — quartos e metades", expanded=False):
                for start in range(0, len(available), 3):
                    row = available[start:start + 3]
                    c = st.columns(len(row))
                    for i, (column, label) in enumerate(row):
                        c[i].metric(label, _fmt(_numeric_mean(played, column)))


def render_players(players: pd.DataFrame):
    st.subheader(f"👥 Jogadores — {team}")
    if players.empty:
        st.warning("Nenhum dado individual foi reconstruído para esta equipe.")
        return

    # O resultado da fonte pode trazer várias linhas/categorias para o mesmo atleta.
    # Agrupamos pelo nome e exibimos cada jogador em uma seção retrátil independente.
    player_col = "player" if "player" in players.columns else "Jogador" if "Jogador" in players.columns else None
    if player_col is None:
        st.dataframe(players, use_container_width=True, hide_index=True)
        return

    names = [str(x) for x in players[player_col].dropna().unique()]
    names.sort(key=str.casefold)

    st.caption(f"{len(names)} jogador(es) encontrado(s). Abra somente o atleta que deseja consultar.")

    display_map = {
        "minutes": "Minutos", "points": "Pontos", "two_points_made": "2PT convertidos", "two_points_attempted": "2PT tentados",
        "three_points_made": "3PT convertidos", "three_points_attempted": "3PT tentados", "free_throws_made": "FT convertidos",
        "free_throws_attempted": "FT tentados", "rebounds": "Rebotes", "assists": "Assistências", "steals": "Roubos",
        "blocks": "Tocos", "turnovers": "Turnovers",
    }

    for name in names:
        pdata = players[players[player_col].astype(str) == name].copy()
        with st.expander(f"🏀 {name}", expanded=False):
            metric_cols = []
            for column, label in display_map.items():
                if column in pdata.columns:
                    value = _numeric_mean(pdata, column)
                    if value is not None:
                        metric_cols.append((column, label, value))

            if metric_cols:
                for start in range(0, len(metric_cols), 4):
                    row = metric_cols[start:start + 4]
                    cols = st.columns(len(row))
                    for i, (_, label, value) in enumerate(row):
                        cols[i].metric(f"Média {label}", _fmt(value))

            # Mantém apenas os registros do atleta, sem misturar com outros jogadores.
            raw_cols = [c for c in ["competition", "game_id", "date", "minutes", "points", "two_points_made", "two_points_attempted", "three_points_made", "three_points_attempted", "free_throws_made", "free_throws_attempted", "rebounds", "assists", "steals", "blocks", "turnovers"] if c in pdata.columns]
            if raw_cols:
                st.dataframe(pdata[raw_cols], use_container_width=True, hide_index=True)


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

        render_players(players)

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
                    "Rebotes": "REB" in games.columns,
                    "Assistências": "AST" in games.columns,
                    "Roubos": "STL" in games.columns,
                    "Tocos": "BLK" in games.columns,
                    "Turnovers": "TOV" in games.columns,
                })
            elif competition == "NBB" and not games.empty:
                checks.update({"Placar": {"PF", "PA"}.issubset(games.columns), "Resultado/jogo": {"home", "away", "played"}.issubset(games.columns)})
            st.dataframe(pd.DataFrame([{"Indicador": k, "Status": "✅" if v else "❌"} for k, v in checks.items()]), use_container_width=True, hide_index=True)

        if errors:
            with st.expander(f"⚠️ Erros ({len(errors)})", expanded=False):
                st.dataframe(pd.DataFrame(errors), use_container_width=True, hide_index=True)

        st.caption("Os dados continuam sendo consultados pela mesma fonte; esta alteração reorganiza apenas a apresentação por equipe e jogador.")

    except BasketballSourceError as exc:
        progress.empty()
        st.error(str(exc))
    except Exception as exc:
        progress.empty()
        st.error(f"❌ Teste não concluído: {type(exc).__name__}: {exc}")
