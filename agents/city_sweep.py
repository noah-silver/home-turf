"""City Sweep: maps many teams' fan bars in one city at once, so the city map shows every logo.

One agent call with a few web searches reads city-wide guides (a bar for every NFL team, alumni
watch-party listings), then the Verifier checks each bar, and the results are saved as
per-team cache entries. That makes later team searches in that city free.
"""

from __future__ import annotations

import config
from agents.llm import run_agent
from agents.schemas import CitySweep
from agents.verifier import verify
from core import audit, db
from core.budget import Run

MAX_SWEEP_SPOTS = 30
FOCUSES = ("NFL teams", "college football teams (alumni clubs)", "MLB, NBA, NHL, and soccer supporters' clubs")
SWEEP_CACHE_DAYS = 14


def sweep_key(city: str) -> str:
    return "sweep|" + city.split(",")[0].strip().lower()


def recently_swept(city: str) -> bool:
    return db.cache_get(sweep_key(city), SWEEP_CACHE_DAYS * 24) is not None


def city_sweep(run: Run, city: str, focuses: tuple[str, ...] = FOCUSES) -> dict:
    from core.orchestrator import _link_bar, merge_duplicates, search_key  # local import avoids a cycle

    spots, notes = [], []
    for focus in focuses:
        report = run_agent(run, "city_sweep", f"City: {city}\nFOCUS: {focus}\nCurrent season: {config.CURRENT_SEASON}", CitySweep,
                           tools=[{"type": "web_search"}], max_tool_calls=4, effort="low", max_output_tokens=8000)
        spots += report.spots[:MAX_SWEEP_SPOTS]
        notes.append(report.notes)
        run.add_step("City Sweep", f"{focus}: {len(report.spots)} team-bar pairs")
    # One batched Verifier pass for every team (each candidate carries its own team).
    verified = verify(run, "various teams", city, spots) if spots else []
    by_team: dict[str, list] = {}
    for spot, result in zip(spots, verified):
        if result["status"] != "rejected":
            by_team.setdefault(spot.team.strip(), []).append(result)
    added_teams = 0
    for team, team_results in by_team.items():
        checked = merge_duplicates(team_results)
        for c in checked:
            c["team"] = team
            c["bar_id"] = _link_bar(c, city)
        key = search_key(team, city)
        existing = db.cache_get(key, config.SEARCH_CACHE_DAYS * 24)
        if existing and existing.get("spots"):
            names = {s["bar_name"].lower() for s in existing["spots"]}
            existing["spots"] += [c for c in checked if c["bar_name"].lower() not in names]
            db.cache_put(key, "spots", existing)
        else:
            db.cache_put(key, "spots", {"team": team, "sport": "", "city": city, "spots": checked, "allgames": [],
                                        "club_name": next((c["club_name"] for c in checked if c["club_name"] not in ("", "unknown")), None),
                                        "club_contact_url": None, "search_notes": "Found by a city-wide sweep.", "safety_notes": [], "found_at": db.now_iso()})
        added_teams += 1
    db.cache_put(sweep_key(city), "sweep", {"city": city, "teams": added_teams, "at": db.now_iso()})
    audit.log("city_sweep", run_id=run.run_id, city=city, pairs=len(spots), teams_saved=added_teams)
    run.add_step("City Sweep", f"{added_teams} teams verified and added to the {city.split(',')[0]} map")
    return {"teams": added_teams, "pairs": len(spots), "notes": " ".join(notes)}
