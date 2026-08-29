from __future__ import annotations

from datetime import date, timedelta
from io import StringIO
from zoneinfo import ZoneInfo
import re

import pandas as pd
import requests
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

MANAUS = ZoneInfo("America/Manaus")
NBA_SCHEDULE_URLS = (
    "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json",
    "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json",
)
NBA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
}
NBB_SCHEDULE_URL = "https://lnb.com.br/nbb/tabela-de-jogos/"
NBB_SEASON_ID = "48"  # NBB 2026/2027


def _numeric_mean(df: pd.DataFrame, column: str):
    if column not in df.columns:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def _fmt(value, decimals: int = 1):
    return "—" if value is None else f"{value:.{decimals}f}"


def _to_manaus(value):
    if not value:
        return None
    try:
        dt = pd.to_datetime(str(value), utc=True, errors="coerce")
        if pd.notna(dt):
            return dt.tz_convert(MANAUS)
    except Exception:
        pass
    try:
        dt = pd.to_datetime(str(value), errors="coerce")
        if pd.notna(dt):
            return dt.tz_localize(MANAUS) if dt.tzinfo is None else dt.tz_convert(MANAUS)
    except Exception:
        pass
    return None


def _nba_schedule_games(start_date: date, end_date: date):
    """Carrega o calendário atual da NBA pelo CDN oficial e converte para Manaus."""
    last_error = None
    payload = None
    for url in NBA_SCHEDULE_URLS:
        try:
            r = requests.get(url, headers=NBA_HEADERS, timeout=(10, 30))
            r.raise_for_status()
            payload = r.json()
            break
        except Exception as exc:
            last_error = exc

    if payload is None:
        raise RuntimeError(f"CDN oficial da NBA indisponível: {last_error}")

    schedule = payload.get("leagueSchedule") or {}
    game_dates = schedule.get("gameDates") or []
    selected_team_id = NBA_TEAMS.get(team, (None,))[0]
    rows = []

    for day in game_dates:
        if not isinstance(day, dict):
            continue
        for g in day.get("games") or []:
            if not isinstance(g, dict):
                continue

            gid = str(g.get("gameId") or g.get("gid") or "")
            if not gid:
                continue

            home = g.get("homeTeam") or g.get("h") or {}
            away = g.get("awayTeam") or g.get("v") or {}
            try:
                hid = int(home.get("teamId") or home.get("tid"))
                aid = int(away.get("teamId") or away.get("tid"))
            except (TypeError, ValueError):
                continue

            if selected_team_id and selected_team_id not in (hid, aid):
                continue

            dt = _to_manaus(
                g.get("gameTimeUTC")
                or g.get("gameTimeUtc")
                or g.get("gameDateTimeUTC")
                or g.get("utcTime")
            )
            if dt is None:
                raw_day = g.get("gameDate") or day.get("gameDate")
                raw_time = g.get("gameTimeLocal") or g.get("gameTime")
                if raw_time and raw_day:
                    dt = _to_manaus(f"{raw_day} {raw_time}")
                else:
                    parsed_day = pd.to_datetime(raw_day, errors="coerce")
                    if pd.notna(parsed_day):
                        dt = parsed_day.tz_localize(MANAUS)
            if dt is None or not start_date <= dt.date() <= end_date:
                continue

            status_code = str(g.get("gameStatus") or g.get("statusNum") or "").lower()
            status_text = str(g.get("gameStatusText") or "").strip()
            if status_code in {"3", "final", "finalizado"} or status_text.lower() in {"final", "finalizado"}:
                status = "Finalizado"
            elif status_code in {"2", "live", "inprogress"}:
                status = "Ao vivo"
            else:
                status = "Agendado"

            hs = home.get("score") if home.get("score") is not None else home.get("s")
            aws = away.get("score") if away.get("score") is not None else away.get("s")
            score = f"{hs} x {aws}" if status != "Agendado" and hs not in (None, "") and aws not in (None, "") else "—"

            home_name = home.get("teamName") or home.get("tn") or home.get("teamTricode") or home.get("ta") or str(hid)
            away_name = away.get("teamName") or away.get("tn") or away.get("teamTricode") or away.get("ta") or str(aid)

            rows.append({
                "Data": dt.strftime("%d/%m/%Y"),
                "Hora (Manaus)": dt.strftime("%H:%M"),
                "Casa": home_name,
                "Fora": away_name,
                "Placar": score,
                "Status": status,
                "game_id": gid,
            })

    unique = {(x["Data"], x["Hora (Manaus)"], x["Casa"], x["Fora"], x["game_id"]): x for x in rows}
    return sorted(unique.values(), key=lambda x: (x["Data"], x["Hora (Manaus)"], x["Casa"]))


def _nbb_calendar_games(start_date: date, end_date: date):
    r = requests.get(
        NBB_SCHEDULE_URL,
        params={"season[]": NBB_SEASON_ID},
        headers={"User-Agent": "Mozilla/5.0 Premium-Analytics", "Accept-Language": "pt-BR,pt;q=0.9"},
        timeout=30,
    )
    r.raise_for_status()
    tables = pd.read_html(StringIO(r.text))
    rows = []

    def canonical(value):
        text = str(value or "").strip().casefold()
        for name, aliases in NBB_TEAMS.items():
            for alias in [name, *aliases]:
                if str(alias).strip().casefold() == text:
                    return name
        return None

    for table in tables:
        for _, raw in table.astype(object).iterrows():
            cells = [str(x) for x in raw.tolist()]
            found_teams = []
            for cell in cells:
                c = canonical(cell)
                if c and c not in found_teams:
                    found_teams.append(c)
            if len(found_teams) < 2 or team not in found_teams:
                continue
            text = " | ".join(cells)
            match = re.search(r"(\d{1,2}/\d{1,2}/\d{4}(?:\s+\d{1,2}:\d{2})?)", text)
            if not match:
                continue
            dt = pd.to_datetime(match.group(1), dayfirst=True, errors="coerce")
            if pd.isna(dt):
                continue
            dt = dt.tz_localize(MANAUS)
            if not start_date <= dt.date() <= end_date:
                continue
            score = "—"
            for cell in cells:
                sm = re.search(r"(?<!\d)(\d{1,3})\s*[xX]\s*(\d{1,3})(?!\d)", cell)
                if sm:
                    score = f"{sm.group(1)} x {sm.group(2)}"
                    break
            rows.append({
                "Data": dt.strftime("%d/%m/%Y"),
                "Hora (Manaus)": dt.strftime("%H:%M"),
                "Casa": found_teams[0],
                "Fora": found_teams[1],
                "Placar": score,
                "Status": "Finalizado" if score != "—" else "Agendado",
                "game_id": "—",
            })
    unique = {(x["Data"], x["Hora (Manaus)"], x["Casa"], x["Fora"], x["Placar"]): x for x in rows}
    return sorted(unique.values(), key=lambda x: (x["Data"], x["Hora (Manaus)"], x["Casa"]))


def render_calendar():
    st.subheader(f"📅 Calendário — {competition} • {team}")
    c1, c2 = st.columns(2)
    start_date = c1.date_input("De", value=date.today(), key="basket_start")
    end_date = c2.date_input("Até", value=date.today() + timedelta(days=45), key="basket_end")
    if end_date < start_date:
        st.error("A data final não pode ser anterior à data inicial.")
        return
    if st.button("🔄 Carregar calendário", use_container_width=True):
        try:
            with st.spinner(f"Consultando calendário {competition}..."):
                rows = _nba_schedule_games(start_date, end_date) if competition == "NBA" else _nbb_calendar_games(start_date, end_date)
            if rows:
                st.success(f"{len(rows)} partida(s) encontrada(s). Horários convertidos para Manaus.")
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.info("Nenhuma partida encontrada para a equipe e período selecionados.")
        except Exception as exc:
            st.error(f"❌ Não foi possível carregar o calendário: {type(exc).__name__}: {exc}")


render_calendar()


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
                    "Placar": {"PF", "PA"}.issubset(games.columns), "Q1": {"Q1_PF", "Q1_PA"}.issubset(games.columns),
                    "Q2": {"Q2_PF", "Q2_PA"}.issubset(games.columns), "Q3": {"Q3_PF", "Q3_PA"}.issubset(games.columns),
                    "Q4": {"Q4_PF", "Q4_PA"}.issubset(games.columns), "H1": {"H1_PF", "H1_PA"}.issubset(games.columns),
                    "H2": {"H2_PF", "H2_PA"}.issubset(games.columns), "Rebotes": "REB" in games.columns,
                    "Assistências": "AST" in games.columns, "Roubos": "STL" in games.columns, "Tocos": "BLK" in games.columns,
                    "Turnovers": "TOV" in games.columns,
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
