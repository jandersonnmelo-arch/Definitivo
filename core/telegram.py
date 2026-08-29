import requests
import streamlit as st


def _secret(*names):
    for name in names:
        try:
            value = st.secrets.get(name)
        except Exception:
            value = None
        if value not in (None, ""):
            return value
    return None


def telegram_configured():
    return bool(
        _secret("BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN")
        and _secret("CHAT_ID", "TELEGRAM_CHAT_ID", "TELEGRAM_GROUP_ID")
    )


def format_analysis_message(match, analysis, competition, kickoff):
    p = analysis.get("probabilities") or {}
    mk = analysis.get("markets") or {}
    lines = [
        "⚽ ARENA 360 • ANÁLISE PRÉ-JOGO",
        "",
        f"🏆 {competition}",
        f"⚔️ {match.get('home_name', 'Casa')} × {match.get('away_name', 'Fora')}",
        f"🕐 {kickoff} — Manaus",
        "",
        "🔮 PROBABILIDADES",
        f"🏠 Casa: {p.get('home', '—')}%",
        f"🤝 Empate: {p.get('draw', '—')}%",
        f"✈️ Fora: {p.get('away', '—')}%",
        f"⚽ xG: {analysis.get('xg_home', '—')} × {analysis.get('xg_away', '—')}",
        "",
        "📊 BASE ESTATÍSTICA",
    ]

    base = [
        ("goals_for", "Gols feitos"),
        ("goals_against", "Gols sofridos"),
        ("shots", "Finalizações"),
        ("shots_on_target", "Finalizações no alvo"),
        ("effectivetackles", "Desarmes"),
        ("corners", "Escanteios"),
        ("fouls", "Faltas"),
        ("passes_completed", "Passes certos"),
        ("saves", "Defesas"),
        ("yellow_cards", "Cartões amarelos"),
        ("red_cards", "Cartões vermelhos"),
        ("player_throws", "Laterais"),
        ("woodwork", "Na trave"),
        ("offsides", "Impedimentos"),
        ("goal_kicks", "Tiros de meta"),
    ]
    home = analysis.get("home") or {}
    away = analysis.get("away") or {}
    for key, label in base:
        hv, av = home.get(key), away.get(key)
        if hv is not None or av is not None:
            lines.append(f"• {label}: {hv if hv is not None else '—'} × {av if av is not None else '—'}")

    lines += ["", "🎯 MERCADOS"]
    market_labels = [
        ("gols", "Gols"),
        ("finalizacoes", "Finalizações"),
        ("finalizacoes_no_alvo", "No alvo"),
        ("desarmes_efetivos", "Desarmes"),
        ("escanteios", "Escanteios"),
        ("faltas", "Faltas"),
        ("passes_certos", "Passes certos"),
        ("defesas", "Defesas"),
        ("cartoes_amarelos", "Cartões amarelos"),
        ("cartoes_vermelhos", "Cartões vermelhos"),
        ("laterais", "Laterais"),
        ("impedimentos", "Impedimentos"),
        ("tiros_de_meta", "Tiros de meta"),
    ]
    for key, label in market_labels:
        obj = mk.get(key) or {}
        expected = obj.get("total_expected")
        lines_obj = obj.get("lines") or {}
        if expected is None and not lines_obj:
            continue
        if lines_obj:
            for line, probability in lines_obj.items():
                under = (obj.get("under_lines") or {}).get(str(line), obj.get("under_probability"))
                lines.append(f"• {label} +{line}: {probability}% | -{line}: {under if under is not None else '—'}% | média {expected}")
        else:
            lines.append(f"• {label}: média {expected}")

    btts = mk.get("gols", {}).get("ambas_marcam") if isinstance(mk.get("gols"), dict) else analysis.get("btts")
    if btts is not None:
        lines.append(f"• Ambas marcam — SIM: {btts}%")

    exact = (mk.get("gols") or {}).get("exact_total") or {}
    if exact:
        lines += ["", "⚽ DISTRIBUIÇÃO DE GOLS"]
        lines.append(" • ".join(f"{k}: {v}%" for k, v in exact.items()))

    lines += [
        "",
        f"📚 Amostra: {analysis.get('sample_home', 0)} casa / {analysis.get('sample_away', 0)} fora",
        "📌 Dados calculados somente a partir do histórico persistido.",
    ]

    message = "\n".join(lines)
    # Telegram limita mensagens de texto a 4096 caracteres.
    if len(message) > 4000:
        message = message[:3950] + "\n\n… mensagem reduzida por limite do Telegram."
    return message


def send_analysis_to_telegram(message):
    token = _secret("BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN")
    chat_id = _secret("CHAT_ID", "TELEGRAM_CHAT_ID", "TELEGRAM_GROUP_ID")
    if not token or not chat_id:
        return False, "Telegram não configurado nos Secrets (BOT_TOKEN/CHAT_ID)."

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
            timeout=20,
        )
        data = response.json()
    except Exception as exc:
        return False, f"Falha de conexão com o Telegram: {exc}"

    if response.ok and data.get("ok"):
        return True, "Análise enviada ao Telegram."

    description = data.get("description") or f"HTTP {response.status_code}"
    return False, f"Telegram recusou o envio: {description}"
