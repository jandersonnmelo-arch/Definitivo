from __future__ import annotations

from datetime import date, datetime, timedelta

from core.mma import event_page, included, items, rel_id, clean, to_date, fighter_profile, history


def upcoming_fights(days: int = 60, start: date | None = None):
    """Return scheduled UFC fights in the next N days from the UFC JSON:API."""
    start = start or date.today()
    end = start + timedelta(days=days)
    rows = []

    # UFC events are paginated 10 at a time. Stop once the oldest event page
    # is completely before our requested window.
    for offset in range(0, 500, 10):
        payload = event_page(offset)
        events = items(payload)
        if not events:
            break
        inc = included(payload)
        page_dates = []

        for event in events:
            ea = event.get("attributes", {})
            event_date = to_date(
                ea.get("fight_card_time_main")
                or ea.get("fight_card_time_prelims")
                or ea.get("fight_card_time_early")
            )
            if event_date:
                page_dates.append(event_date)
            if not event_date or not (start <= event_date <= end):
                continue

            event_name = clean(ea.get("title")) or "Evento UFC"
            for ref in event.get("relationships", {}).get("fights", {}).get("data", []):
                fight = inc.get(ref.get("id"), {})
                if not fight:
                    continue
                red_id = rel_id(fight, "red_corner")
                blue_id = rel_id(fight, "blue_corner")
                red = inc.get(red_id, {})
                blue = inc.get(blue_id, {})
                red_name = clean(red.get("attributes", {}).get("title"))
                blue_name = clean(blue.get("attributes", {}).get("title"))
                if not red_name or not blue_name:
                    continue
                fa = fight.get("attributes", {})
                rows.append({
                    "event_date": event_date.isoformat(),
                    "event_name": event_name,
                    "fight_id": fight.get("id"),
                    "red_id": red_id,
                    "blue_id": blue_id,
                    "red_name": red_name,
                    "blue_name": blue_name,
                    "weight_class": clean(fa.get("weight_class")) or clean(fa.get("weightclass")) or "—",
                    "status": clean(fa.get("status")) or "Agendada",
                    "fight_title": clean(fa.get("title")) or f"{red_name} x {blue_name}",
                })

        # Events are sorted newest first by the API request. Once the whole
        # page is older than the requested start date there is no need to scan further.
        if page_dates and max(page_dates) < start:
            break

    unique = {}
    for row in rows:
        key = row["fight_id"] or (row["event_date"], row["red_name"], row["blue_name"])
        unique[key] = row
    return sorted(unique.values(), key=lambda x: (x["event_date"], x["event_name"], x["red_name"]))


def selected_fight_analysis(fight):
    """Load both fighters from a selected calendar fight and build their last 5 fights."""
    result = {"fight": fight, "fighters": []}
    for fighter_id, fighter_name in (
        (fight.get("red_id"), fight.get("red_name")),
        (fight.get("blue_id"), fight.get("blue_name")),
    ):
        profile = None
        try:
            if fighter_id:
                # Search by exact name is the stable public endpoint used by the
                # validated laboratory; it also returns the canonical UFC athlete id.
                profile = fighter_profile(fighter_name)
            if not profile:
                continue
            rows = history(profile)
            wins = sum(1 for row in rows if row.get("Resultado") == "V")
            losses = sum(1 for row in rows if row.get("Resultado") == "D")
            known = wins + losses
            rounds = []
            for row in rows:
                try:
                    value = float(row.get("Round"))
                    rounds.append(value)
                except (TypeError, ValueError):
                    pass
            result["fighters"].append({
                "name": profile["name"],
                "profile": profile,
                "history": rows,
                "wins_last5": wins,
                "losses_last5": losses,
                "win_rate_last5": (100.0 * wins / known) if known else None,
                "avg_round_last5": (sum(rounds) / len(rounds)) if rounds else None,
            })
        except Exception as exc:
            result["fighters"].append({
                "name": fighter_name,
                "profile": None,
                "history": [],
                "error": f"{type(exc).__name__}: {exc}",
            })
    return result
