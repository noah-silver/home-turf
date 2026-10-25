"""My Season: a fan's personal game-day plan for their favorite team.

1. Schedule agent: the team's season (cached a day).
2. Trip Parser agent: turns "Boston until Oct 3, then Chicago" into a city for each game date.
3. Code: for each city, verified watch spots from cache; uncached cities get a live search
   (in parallel, at most MAX_NEW_CITIES per plan to cap cost). Kickoffs are converted to local time.
4. Season Planner agent: picks a bar and a backup for every game from those candidates only
   (validated after), plus a short tip. The plan can be downloaded as a calendar (.ics).
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
from agents.llm import run_agent, untrusted
from agents.schedule import get_schedule
from agents.schemas import SeasonItinerary, TripParse
from core import db
from core.budget import Run
from core.citymap import known_points

MAX_NEW_CITIES = 4
MAX_GAMES = 12  # long NBA/NHL/MLB seasons: plan the next 12 games
ET = ZoneInfo("America/New_York")
STATE_TZ = {
    **{s: "America/New_York" for s in "CT DE DC FL GA ME MD MA MI NH NJ NY NC OH PA RI SC VT VA WV IN KY".split()},
    **{s: "America/Chicago" for s in "AL AR IL IA KS LA MN MS MO NE ND OK SD TN TX WI".split()},
    **{s: "America/Denver" for s in "CO ID MT NM UT WY".split()},
    "AZ": "America/Phoenix", "NV": "America/Los_Angeles", "CA": "America/Los_Angeles", "OR": "America/Los_Angeles",
    "WA": "America/Los_Angeles", "AK": "America/Anchorage", "HI": "Pacific/Honolulu", "PR": "America/Puerto_Rico",
    "UK": "Europe/London", "Ireland": "Europe/Dublin", "ON": "America/Toronto", "Mexico": "America/Mexico_City",
}


def city_tz(city: str | None) -> ZoneInfo:
    if not city or "," not in city:
        return ET
    return ZoneInfo(STATE_TZ.get(city.split(",")[-1].strip(), "America/New_York"))


def kickoff_local(date: str, kickoff_et: str, city: str | None) -> tuple[datetime | None, str]:
    """('3:30 PM ET' on a date) -> aware datetime in the city's time zone, and a label like '12:30 PM PT'."""
    m = re.search(r"(\d{1,2}):?(\d{2})?\s*(AM|PM)", kickoff_et or "", re.I)
    if not m:
        return None, "TBD"
    hour = int(m.group(1)) % 12 + (12 if m.group(3).upper() == "PM" else 0)
    start = datetime.fromisoformat(date).replace(hour=hour, minute=int(m.group(2) or 0), tzinfo=ET)
    local = start.astimezone(city_tz(city))
    return local, local.strftime("%-I:%M %p ") + local.tzname()


def parse_trip(run: Run, games: list[dict], text: str, default_city: str | None) -> dict[str, str | None]:
    if not text.strip():
        return {g["date"]: default_city for g in games}
    sched = "\n".join(f"- {g['date']}: vs {g['opponent']} ({g['home_away']})" for g in games)
    prompt = f"Schedule:\n{sched}\n\nDefault city if nothing else applies: {default_city or 'none'}\n\n" + untrusted("FAN'S TRAVEL NOTES", text, 1500)
    parsed = run_agent(run, "trip_parser", prompt, TripParse, effort="low", max_output_tokens=2500)
    cities = {a.date: a.city for a in parsed.assignments}
    run.add_step("Trip Parser", f"placed {sum(1 for c in cities.values() if c)} of {len(games)} games in a city")
    return {g["date"]: cities.get(g["date"]) or default_city for g in games}


def _candidates(team: str, city: str) -> list[dict]:
    from core.orchestrator import search_key

    out = []
    cached = db.cache_get(search_key(team, city), config.SEARCH_CACHE_DAYS * 24)
    for s in (cached or {}).get("spots", []):
        if s["status"] in ("confirmed", "likely", "unverified"):
            out.append({"bar": s["bar_name"], "status": s["status"], "club": s.get("club_name") or "", "bar_id": s.get("bar_id"), "address": s.get("address", "")})
    for a in (cached or {}).get("allgames", []):
        out.append({"bar": a["bar_name"], "status": "shows every game", "club": "", "bar_id": a.get("bar_id"), "address": a.get("address", "")})
    for p in known_points(city):
        for t in p["teams"]:
            if t["team"].lower() == team.lower() and t["status"] == "partner" and all(o["bar"] != p["bar_name"] for o in out):
                out.append({"bar": p["bar_name"], "status": "Home Turf partner", "club": t["club"], "bar_id": p["bar_id"], "address": p["address"]})
    return out


def plan_season(run: Run, team: str, sport: str | None, trip_text: str, default_city: str | None) -> dict:
    from core.orchestrator import _spots_for, search_key

    sched = get_schedule(run, team)
    if not sched or not sched.games:
        return {"error": f"Couldn't find a {config.CURRENT_SEASON} schedule for {team}."}
    today = datetime.now(ET).date().isoformat()
    games = [g.model_dump() for g in sched.games]
    upcoming = ([g for g in games if g["date"] >= today] or games)[:MAX_GAMES]
    cities = parse_trip(run, upcoming, trip_text, default_city)

    # Scout cities we know nothing about yet (in parallel, capped).
    needed = sorted({c for c in cities.values() if c})
    unknown = [c for c in needed if not db.cache_get(search_key(team, c), config.SEARCH_CACHE_DAYS * 24)]
    to_scout, skipped = unknown[:MAX_NEW_CITIES], unknown[MAX_NEW_CITIES:]
    if to_scout:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda c: _spots_for(run, team, c, sport), to_scout))
        run.add_step("Scout", f"searched {len(to_scout)} new cities: {', '.join(c.split(',')[0] for c in to_scout)}")
    cand = {c: _candidates(team, c) for c in needed}

    rows = []
    for g in upcoming:
        city = cities.get(g["date"])
        local, label = kickoff_local(g["date"], g["kickoff_et"], city)
        rows.append({**g, "city": city, "kickoff_local": label, "start": local.isoformat() if local else None,
                     "candidates": cand.get(city, []) if city else []})
    lines = []
    for r in rows:
        opts = "; ".join(f"{c['bar']} [{c['status']}{', ' + c['club'] if c['club'] else ''}]" for c in r["candidates"][:5]) or "none known"
        lines.append(f"- {r['date']} {r['home_away']} vs {r['opponent']}, kickoff {r['kickoff_local']}, city: {r['city'] or 'unknown'}; candidates: {opts}")
    prompt = f"Team: {team}\nGames:\n" + untrusted("GAMES AND CANDIDATE BARS", "\n".join(lines), 9000)
    plan = run_agent(run, "season_planner", prompt, SeasonItinerary, effort="low", max_output_tokens=5000)

    picks = {p.date: p for p in plan.games}
    for r in rows:
        p = picks.get(r["date"])
        names = {c["bar"]: c for c in r["candidates"]}
        pick = p.pick if p and p.pick in names else (r["candidates"][0]["bar"] if r["candidates"] else None)
        backup = p.backup if p and p.backup in names and p.backup != pick else None
        r.update(pick=names.get(pick), backup=names.get(backup), tip=p.tip if p else "")
    run.add_step("Season Planner", f"{sum(1 for r in rows if r['pick'])} of {len(rows)} games have a bar picked across {len(needed)} cities")
    return {"team": team, "games": rows, "summary": plan.summary, "skipped_cities": skipped, "source": sched.source_url}


def to_ics(plan: dict) -> str:
    def esc(t: str) -> str:
        out = (t or "").replace("\\", "\\\\")
        for ch in (",", ";"):
            out = out.replace(ch, "\\" + ch)
        return out.replace("\n", "\\n")

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Home Turf//My Season//EN", "CALSCALE:GREGORIAN"]
    stamp = datetime.now(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    for g in plan["games"]:
        bar = g.get("pick")
        title = f"{plan['team']} vs {g['opponent']}" + (f" · {bar['bar']}" if bar else "")
        lines += ["BEGIN:VEVENT", f"UID:{g['date']}-{re.sub(r'[^a-z0-9]', '', plan['team'].lower())}@hometurf", f"DTSTAMP:{stamp}"]
        if g.get("start"):
            start = datetime.fromisoformat(g["start"]).astimezone(ZoneInfo("UTC"))
            lines += [f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}", f"DTEND:{(start + timedelta(hours=3, minutes=30)).strftime('%Y%m%dT%H%M%SZ')}"]
        else:
            day = g["date"].replace("-", "")
            lines += [f"DTSTART;VALUE=DATE:{day}"]
        lines += [f"SUMMARY:{esc(title)}", f"LOCATION:{esc((bar or {}).get('address') or g.get('city') or '')}",
                  f"DESCRIPTION:{esc(g.get('tip', '') + (' Backup: ' + g['backup']['bar'] if g.get('backup') else ''))}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


def save_plan(user_id: str | None, team: str, trip_text: str, plan: dict) -> None:
    db.insert("plans", {"user_id": user_id or "guest", "team": team, "trip_text": trip_text[:1500], "payload": json.dumps(plan, default=str), "created_at": db.now_iso()})
