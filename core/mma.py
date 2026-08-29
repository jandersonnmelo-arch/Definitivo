import re
import time
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

BASE = "https://www.ufc.com/jsonapi"
VERSION = "MMA histórico UFC · fonte oficial UFC JSON:API · exatamente 5 lutas"
MMA_LUTAS = 5
HEADERS = {
    "User-Agent": "Premium Football Analytics / MMA Lab",
    "Accept": "application/vnd.api+json",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def to_date(value):
    text = clean(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def pct(value):
    if value is None:
        return "—"
    try:
        return "{:.1f}%".format(float(value))
    except (TypeError, ValueError):
        return str(value)


@st.cache_data(ttl=21600, show_spinner=False)
def api_get(path, params=None):
    last_exc = None
    for attempt in range(3):
        try:
            response = requests.get(
                BASE + path,
                params=params or {},
                headers=HEADERS,
                timeout=(15, 90),
            )
            response.raise_for_status()
            return response.json()
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except requests.HTTPError:
            raise
    raise last_exc


def items(payload):
    data = payload.get("data", []) if isinstance(payload, dict) else []
    return data if isinstance(data, list) else [data]


def included(payload):
    return {x.get("id"): x for x in payload.get("included", []) if x.get("id")}


def rel_id(item, name):
    data = item.get("relationships", {}).get(name, {}).get("data")
    return data.get("id") if isinstance(data, dict) else None


@st.cache_data(ttl=21600, show_spinner=False)
def search_fighters(query):
    payload = api_get(
        "/node/athlete",
        {
            "filter[title][value]": query,
            "filter[title][operator]": "CONTAINS",
            "page[limit]": 30,
        },
    )
    result = []
    for item in items(payload):
        attrs = item.get("attributes", {})
        name = clean(attrs.get("title"))
        if name:
            result.append({
                "id": item.get("id"),
                "name": name,
                "fightmetric_id": attrs.get("fightmetric_id"),
            })
    return result


@st.cache_data(ttl=21600, show_spinner=False)
def fighter_profile(name):
    payload = api_get(
        "/node/athlete",
        {
            "filter[title]": name,
            "include": "athlete_stat,athlete_ranking,stats_weight_class,fighting_style,gym,athlete_status",
            "page[limit]": 1,
        },
    )
    data = items(payload)
    if not data:
        return None

    athlete = data[0]
    inc = included(payload)
    stat = {}
    ranking = {}

    for relationship in athlete.get("relationships", {}).values():
        ref = relationship.get("data")
        refs = ref if isinstance(ref, list) else [ref]
        for obj_ref in refs:
            if not isinstance(obj_ref, dict):
                continue
            obj = inc.get(obj_ref.get("id"), {})
            if obj.get("type") == "athlete_stat--athlete_stat":
                stat = obj.get("attributes", {})
            elif obj.get("type") == "athlete_ranking--athlete_ranking":
                ranking = obj.get("attributes", {})

    return {
        "id": athlete.get("id"),
        "name": clean(athlete.get("attributes", {}).get("title") or name),
        "attrs": athlete.get("attributes", {}),
        "stat": stat,
        "ranking": ranking,
    }


@st.cache_data(ttl=21600, show_spinner=False)
def event_page(offset):
    return api_get(
        "/node/event",
        {
            "sort": "-fight_card_time_main",
            "page[limit]": 10,
            "page[offset]": offset,
            "include": "fights,fights.red_corner,fights.blue_corner,venue",
        },
    )


def history(profile):
    """Reconstrói exatamente as últimas 5 lutas oficiais disponíveis.

    Não usa janela temporal e não cria lutas complementares artificiais.
    A data é preservada somente como informação histórica e para ordenação.
    """
    target_id = profile["id"]
    target_name = profile["name"].lower()
    rows = []

    for offset in range(0, 500, 10):
        if len(rows) >= MMA_LUTAS:
            break

        payload = event_page(offset)
        page_events = items(payload)
        if not page_events:
            break

        inc = included(payload)
        events = sorted(
            page_events,
            key=lambda event: to_date(
                event.get("attributes", {}).get("fight_card_time_main")
                or event.get("attributes", {}).get("fight_card_time_prelims")
                or event.get("attributes", {}).get("fight_card_time_early")
            ) or datetime.min.date(),
            reverse=True,
        )

        for event in events:
            if len(rows) >= MMA_LUTAS:
                break

            ea = event.get("attributes", {})
            event_date = to_date(
                ea.get("fight_card_time_main")
                or ea.get("fight_card_time_prelims")
                or ea.get("fight_card_time_early")
            )
            if not event_date:
                continue

            event_name = clean(ea.get("title"))
            fight_refs = event.get("relationships", {}).get("fights", {}).get("data", [])

            for ref in fight_refs:
                if len(rows) >= MMA_LUTAS:
                    break

                fight = inc.get(ref.get("id"), {})
                if not fight:
                    continue

                red_id = rel_id(fight, "red_corner")
                blue_id = rel_id(fight, "blue_corner")
                red = inc.get(red_id, {})
                blue = inc.get(blue_id, {})
                red_name = clean(red.get("attributes", {}).get("title"))
                blue_name = clean(blue.get("attributes", {}).get("title"))

                is_target = (
                    target_id in (red_id, blue_id)
                    or target_name in (red_name.lower(), blue_name.lower())
                )
                if not is_target:
                    continue

                winner_id = rel_id(fight, "fight_final_winner")
                if winner_id == target_id:
                    result = "V"
                elif winner_id in (red_id, blue_id):
                    result = "D"
                else:
                    result = "N/D"

                if target_id == red_id or target_name == red_name.lower():
                    opponent = blue_name
                else:
                    opponent = red_name
                opponent = opponent or blue_name or red_name or "—"

                fa = fight.get("attributes", {})
                rows.append({
                    "Data": event_date.isoformat(),
                    "Evento": event_name,
                    "Luta": clean(fa.get("title")) or "{} x {}".format(red_name, blue_name),
                    "Adversário": opponent,
                    "Resultado": result,
                    "Round": fa.get("round") or "—",
                    "Tempo": fa.get("time") or "—",
                    "Método": clean(fa.get("method")) or "—",
                })

    rows.sort(key=lambda x: x["Data"], reverse=True)
    return rows[:MMA_LUTAS]


def career_table(stat):
    fields = [
        ("Lutas na carreira", "career_fights"),
        ("Vitórias", "career_wins"),
        ("Derrotas", "career_losses"),
        ("Empates", "career_draws"),
        ("No Contest", "career_no_contest"),
        ("Vitórias por KO/TKO", "win_ko"),
        ("Vitórias por finalização", "win_sub"),
        ("Vitórias por decisão", "win_dec"),
        ("Finalizações no 1º round", "first_rd_fin"),
        ("Defesas de título", "title_def"),
        ("Sequência de vitórias", "win_streak"),
    ]
    return pd.DataFrame([
        {"Indicador": label, "Valor": stat.get(key, "—")}
        for label, key in fields
    ])


def technical_table(stat):
    fields = [
        ("Golpes significativos", "sig_strikes_landed", "sig_strikes_attempted"),
        ("Precisão golpes sig.", "sig_strikes_accuracy", None),
        ("Golpes sig./min", "sig_str_land_min", None),
        ("Golpes sig. sofridos/min", "sig_str_abs_min", None),
        ("Defesa de golpes sig.", "sig_str_def", None),
        ("Quedas", "takedowns_landed", "takedowns_attempted"),
        ("Precisão de quedas", "takedown_acuracy", None),
        ("Defesa de quedas", "takedown_defense", None),
        ("Média de quedas", "takedown_average", None),
        ("Média de finalizações", "submission_average", None),
        ("Média de knockdowns", "knockdown_average", None),
        ("Tempo médio de luta", "avg_fight_time", None),
    ]
    rows = []
    for label, first, second in fields:
        value = stat.get(first, "—")
        if second:
            value = "{} / {}".format(stat.get(first, "0"), stat.get(second, "0"))
        rows.append({"Indicador": label, "Valor": value})
    return pd.DataFrame(rows)


def strike_table(stat):
    fields = [
        ("Em pé", "stand_str_land", "stand_str_att"),
        ("Clinch", "clinch_str_land", "clinch_str_att"),
        ("Solo", "ground_str_land", "ground_str_att"),
        ("Cabeça", "head_str_land", "head_str_att"),
        ("Corpo", "body_str_land", "body_str_att"),
        ("Perna", "leg_str_land", "leg_str_att"),
    ]
    return pd.DataFrame([
        {"Zona": label, "Acertos": stat.get(land, "0"), "Tentativas": stat.get(att, "0")}
        for label, land, att in fields
    ])


def coverage(rows, profile, requested):
    stat = profile.get("stat", {}) if profile else {}
    checks = {
        "Lutador / perfil": bool(profile),
        "Quantidade solicitada": len(rows) == requested,
        "Histórico por lutas": len(rows) == MMA_LUTAS,
        "Resultado das lutas": bool(rows) and all(x["Resultado"] != "N/D" for x in rows),
        "Adversários": bool(rows) and all(x["Adversário"] for x in rows),
        "Evento e data": bool(rows) and all(x["Evento"] and x["Data"] for x in rows),
        "Estatísticas de carreira": bool(stat),
        "Golpes por posição": all(stat.get(k) is not None for k in ("stand_str_land", "clinch_str_land", "ground_str_land")),
        "Golpes por alvo": all(stat.get(k) is not None for k in ("head_str_land", "body_str_land", "leg_str_land")),
        "Quedas / finalizações / KD": all(stat.get(k) is not None for k in ("takedowns_landed", "submission_average", "knockdown_average")),
    }
    return pd.DataFrame([
        {"Indicador": label, "OK": "✅" if ok else "⚠️"}
        for label, ok in checks.items()
    ])
