from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re
import requests

NBA_TEAMS = {
    "Atlanta Hawks": (1610612737, "ATL"), "Boston Celtics": (1610612738, "BOS"),
    "Brooklyn Nets": (1610612751, "BKN"), "Charlotte Hornets": (1610612766, "CHA"),
    "Chicago Bulls": (1610612741, "CHI"), "Cleveland Cavaliers": (1610612739, "CLE"),
    "Dallas Mavericks": (1610612742, "DAL"), "Denver Nuggets": (1610612743, "DEN"),
    "Detroit Pistons": (1610612765, "DET"), "Golden State Warriors": (1610612744, "GSW"),
    "Houston Rockets": (1610612745, "HOU"), "Indiana Pacers": (1610612754, "IND"),
    "LA Clippers": (1610612746, "LAC"), "Los Angeles Lakers": (1610612747, "LAL"),
    "Memphis Grizzlies": (1610612763, "MEM"), "Miami Heat": (1610612748, "MIA"),
    "Milwaukee Bucks": (1610612749, "MIL"), "Minnesota Timberwolves": (1610612750, "MIN"),
    "New Orleans Pelicans": (1610612740, "NOP"), "New York Knicks": (1610612752, "NYK"),
    "Oklahoma City Thunder": (1610612760, "OKC"), "Orlando Magic": (1610612753, "ORL"),
    "Philadelphia 76ers": (1610612755, "PHI"), "Phoenix Suns": (1610612756, "PHX"),
    "Portland Trail Blazers": (1610612757, "POR"), "Sacramento Kings": (1610612758, "SAC"),
    "San Antonio Spurs": (1610612759, "SAS"), "Toronto Raptors": (1610612761, "TOR"),
    "Utah Jazz": (1610612762, "UTA"), "Washington Wizards": (1610612764, "WAS"),
}

SCHEDULE_URL = "https://data.nba.com/data/10s/v2015/json/mobile_teams/nba/{season_start}/league/00_full_schedule.json"
BOXSCORE_URLS = (
    "https://nba-prod-us-east-1-mediaops-stats.s3.amazonaws.com/NBA/liveData/boxscore/boxscore_{game_id}.json",
    "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json",
)
HEADERS = {"User-Agent": "Mozilla/5.0 Premium-Analytics", "Accept": "application/json, text/plain, */*", "Referer": "https://www.nba.com/"}
MANAUS = ZoneInfo("America/Manaus")
NBA_CALENDAR_SEASON = "2026-27"


def _num(value):
    try: return float(value)
    except (TypeError, ValueError): return 0.0


def _date(value):
    text = str(value or "")[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try: return datetime.strptime(text, fmt).date()
        except ValueError: pass
    return None


def _season_start(season: str) -> int:
    return int(str(season)[:4])


def _schedule(season: str):
    r = requests.get(SCHEDULE_URL.format(season_start=_season_start(season)), headers=HEADERS, timeout=(8, 20))
    r.raise_for_status()
    return r.json()


def _games(payload):
    found = []
    def walk(obj):
        if isinstance(obj, dict):
            if obj.get("gid") and (obj.get("gcode") or obj.get("gdte")): found.append(obj)
            for value in obj.values(): walk(value)
        elif isinstance(obj, list):
            for value in obj: walk(value)
    walk(payload)
    return list({str(g["gid"]): g for g in found}.values())


def _team_games(schedule, team_id, start, end):
    rows = []
    for g in _games(schedule):
        gid = str(g.get("gid", "")); gd = _date(g.get("gdte") or g.get("gameDate"))
        if not gid.startswith("002") or not gd or not start <= gd <= end: continue
        h, a = g.get("h") or {}, g.get("v") or {}
        try: hid, aid = int(h.get("tid")), int(a.get("tid"))
        except (TypeError, ValueError): continue
        if team_id not in (hid, aid): continue
        rows.append({"game_id": gid, "date": gd, "home_id": hid, "away_id": aid, "home": h.get("ta"), "away": a.get("ta")})
    return sorted(rows, key=lambda x: x["date"])


def _parse_utc(value):
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(MANAUS)
    except ValueError:
        return None


def _calendar_datetime(game):
    for key in ("gdtutc", "gameTimeUTC", "gameDateTimeUTC", "utcTime"):
        dt = _parse_utc(game.get(key))
        if dt:
            return dt
    # Fallback for schedule payloads that expose only date/time fields.
    gd = str(game.get("gdte") or game.get("gameDate") or "")[:10]
    tm = str(game.get("etm") or game.get("gameTime") or "").strip()
    if gd and tm:
        for fmt in ("%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M"):
            try:
                return datetime.strptime(f"{gd} {tm}", fmt).replace(tzinfo=ZoneInfo("America/New_York")).astimezone(MANAUS)
            except ValueError:
                pass
    if gd:
        d = _date(gd)
        return datetime.combine(d, datetime.min.time(), tzinfo=MANAUS) if d else None
    return None


def collect_calendar(start_date, end_date, season: str = NBA_CALENDAR_SEASON):
    """Retorna o calendário NBA no fuso de Manaus, incluindo jogos futuros."""
    schedule = _schedule(season)
    rows = []
    for g in _games(schedule):
        gid = str(g.get("gid", ""))
        if not gid.startswith("002"):
            continue
        dt = _calendar_datetime(g)
        if not dt or not start_date <= dt.date() <= end_date:
            continue
        h, a = g.get("h") or {}, g.get("v") or {}
        status_code = str(g.get("stt") or g.get("statusNum") or "").lower()
        if status_code in {"3", "final", "finalizado", "post"}:
            status = "Finalizado"
        elif status_code in {"2", "live", "inprogress", "1st", "2nd", "3rd", "4th"}:
            status = "Ao vivo"
        else:
            status = "Agendado"
        hs = h.get("s", h.get("score")); aws = a.get("s", a.get("score"))
        rows.append({
            "competition": "NBA", "game_id": gid, "datetime": dt, "date": dt.date(), "time": dt.strftime("%H:%M"),
            "home": h.get("tn") or h.get("ta") or h.get("tc"), "away": a.get("tn") or a.get("ta") or a.get("tc"),
            "home_score": hs if status != "Agendado" else None, "away_score": aws if status != "Agendado" else None,
            "status": status, "season": season,
        })
    return sorted(rows, key=lambda x: x["datetime"])


def _boxscore(game_id):
    errors = []
    for url in BOXSCORE_URLS:
        try:
            r = requests.get(url.format(game_id=game_id), headers=HEADERS, timeout=(5, 15)); r.raise_for_status()
            data = r.json(); data["_source"] = url.split("/")[2]; return data
        except Exception as exc: errors.append(str(exc))
    raise RuntimeError(f"NBA box score {game_id} indisponível: {' | '.join(errors)}")


def _team_pair(game, team_id):
    for side, other in (("homeTeam", "awayTeam"), ("awayTeam", "homeTeam")):
        team, opp = game.get(side) or {}, game.get(other) or {}
        if int(team.get("teamId", -1)) == int(team_id): return team, opp
    raise RuntimeError(f"Time {team_id} não encontrado no box score.")


def _periods(team, opp):
    a = {int(x.get("period")): _num(x.get("score")) for x in team.get("periods") or [] if str(x.get("period", "")).isdigit()}
    b = {int(x.get("period")): _num(x.get("score")) for x in opp.get("periods") or [] if str(x.get("period", "")).isdigit()}
    out = {}
    for q in range(1, 5):
        pf, pa = a.get(q), b.get(q); out.update({f"Q{q}_PF": pf, f"Q{q}_PA": pa, f"Q{q}_SALDO": pf-pa if pf is not None and pa is not None else None})
    h1f, h1a = sum(a.get(q, 0) for q in (1,2)), sum(b.get(q, 0) for q in (1,2)); h2f, h2a = sum(a.get(q, 0) for q in (3,4)), sum(b.get(q, 0) for q in (3,4))
    out.update({"H1_PF": h1f, "H1_PA": h1a, "H1_SALDO": h1f-h1a, "H2_PF": h2f, "H2_PA": h2a, "H2_SALDO": h2f-h2a})
    return out


def _game_row(game, team_id, fallback):
    team, opp = _team_pair(game, team_id); s = team.get("statistics") or {}; pf, pa = _num(team.get("score")), _num(opp.get("score"))
    row = {"competition":"NBA", "game_id":str(game.get("gameId") or fallback["game_id"]), "date":_date(game.get("gameTimeLocal")) or fallback["date"], "home":int(team.get("teamId",-1))==int((game.get("homeTeam") or {}).get("teamId",-2)), "PF":pf,"PA":pa,"FGM":_num(s.get("fieldGoalsMade")),"FGA":_num(s.get("fieldGoalsAttempted")),"3PM":_num(s.get("threePointersMade")),"3PA":_num(s.get("threePointersAttempted")),"FTM":_num(s.get("freeThrowsMade")),"FTA":_num(s.get("freeThrowsAttempted")),"REB":_num(s.get("reboundsTotal")),"AST":_num(s.get("assists")),"STL":_num(s.get("steals")),"BLK":_num(s.get("blocks")),"TOV":_num(s.get("turnoversTotal",s.get("turnovers")))}
    row.update(_periods(team, opp)); return row


def _player_rows(game, team_id, game_date):
    team, _ = _team_pair(game, team_id); rows=[]
    for p in team.get("players") or []:
        s=p.get("statistics") or {}
        if not s: continue
        rows.append({"competition":"NBA","game_id":str(game.get("gameId")),"PLAYER_ID":int(p.get("personId") or 0),"Jogador":p.get("name") or p.get("nameI") or "Desconhecido","Data":game_date.isoformat(),"MIN":_num(s.get("minutesCalculated") or s.get("minutes")),"PTS":_num(s.get("points")),"2PM":_num(s.get("twoPointersMade")),"2PA":_num(s.get("twoPointersAttempted")),"3PM":_num(s.get("threePointersMade")),"3PA":_num(s.get("threePointersAttempted")),"FTM":_num(s.get("freeThrowsMade")),"FTA":_num(s.get("freeThrowsAttempted")),"REB":_num(s.get("reboundsTotal")),"AST":_num(s.get("assists")),"STL":_num(s.get("steals")),"BLK":_num(s.get("blocks")),"TOV":_num(s.get("turnovers")),"JO":1})
    return rows


def collect_team_history(team: str, months: int = 8, season: str = "2025-26"):
    if team not in NBA_TEAMS: raise ValueError(f"Time NBA não reconhecido: {team}")
    team_id,_=NBA_TEAMS[team]; end=date.today(); start=end-timedelta(days=30*months); schedule=_schedule(season); games=_team_games(schedule,team_id,start,end)
    game_rows=[]; player_rows=[]; errors=[]
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures={ex.submit(_boxscore,x["game_id"]):x for x in games}
        for f in as_completed(futures):
            item=futures[f]
            try:
                payload=f.result(); game=payload["game"]; game_rows.append(_game_row(game,team_id,item)); player_rows.extend(_player_rows(game,team_id,item["date"]))
            except Exception as exc: errors.append({"game_id":item["game_id"],"error":str(exc)})
    if not game_rows: raise RuntimeError("NBA encontrou jogos, mas nenhum box score pôde ser reconstruído.")
    return {"competition":"NBA","team":team,"team_id":team_id,"season":season,"start":start,"end":end,"games":game_rows,"players":player_rows,"errors":errors}


def collect_player_stats(team: str, months: int = 8):
    return collect_team_history(team, months)["players"]


def collect_game(game_id: str):
    return _boxscore(str(game_id))
