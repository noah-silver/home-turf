"""Matchmaker: season mode (club -> home bar) and rivalry mode (two clubs -> one bar, one game).

Code does the facts: candidate bars, capacity math, and schedule conflicts. The model only
ranks and explains, and may only pick bar_ids from the candidate list (validated after).
"""

from __future__ import annotations

import json
import re

import config
from agents.llm import run_agent, untrusted
from agents.schedule import get_schedule
from agents.schemas import RivalryPlan, SeasonPlan, TeamSchedule
from core import db
from core.budget import Run

OVERLAP_MINUTES = 210  # a football game plus pregame


def kickoff_minutes(kickoff: str) -> int | None:
    m = re.search(r"(\d{1,2}):?(\d{2})?\s*(AM|PM)", kickoff or "", re.I)
    if not m:
        return None
    hour = int(m.group(1)) % 12 + (12 if m.group(3).upper() == "PM" else 0)
    return hour * 60 + int(m.group(2) or 0)


def find_conflicts(mine: TeamSchedule | None, theirs: TeamSchedule | None, their_club: str) -> list[dict]:
    if not mine or not theirs:
        return []
    out = []
    by_date = {g.date: g for g in theirs.games}
    for g in mine.games:
        other = by_date.get(g.date)
        if not other:
            continue
        a, b = kickoff_minutes(g.kickoff_et), kickoff_minutes(other.kickoff_et)
        if a is None or b is None:
            kind = "possible"
        elif abs(a - b) < OVERLAP_MINUTES:
            kind = "overlap"
        else:
            continue
        out.append(
            {
                "date": g.date,
                "our_game": f"vs {g.opponent} {g.kickoff_et}",
                "their_club": their_club,
                "their_game": f"{theirs.team} vs {other.opponent} {other.kickoff_et}",
                "kind": kind,
            }
        )
    return out


def _city_key(city: str | None) -> str:
    return (city or "").split(",")[0].strip().lower()


MAX_CANDIDATES = 8


def candidate_bars(city: str, teams: tuple[str, ...] = ()) -> list[dict]:
    """Bars with a filled-in profile, plus found bars already known for one of these teams."""
    rows = [b for b in db.query("SELECT * FROM bars") if _city_key(b["city"]) == _city_key(city)]
    team_keys = [t.lower() for t in teams]
    hosts_team = lambda b: any(t in (b["teams_hosted"] or "").lower() for t in team_keys)  # noqa: E731
    # Real bars the web ties to this team (often no profile yet) always make the shortlist, up to 3,
    # so presidents can open their photos, reviews, and Google Maps card; partner profiles fill the rest.
    real = [b for b in rows if not b["is_demo"] and hosts_team(b)][:3]
    partners = sorted([b for b in rows if b["capacity"] and b not in real], key=lambda b: -(b["capacity"] or 0))
    return (real + partners)[:MAX_CANDIDATES]


def _bar_facts(bar: dict) -> dict:
    return {
        "bar_id": bar["id"],
        "name": bar["name"],
        "neighborhood": bar["neighborhood"],
        "capacity": bar["capacity"],
        "tvs": bar["tvs"],
        "sound_policy": bar["sound_policy"],
        "specials": bar["specials"],
        "teams_hosted": bar["teams_hosted"],
        "claimed_profile": bool(bar["claimed"]),
    }


def season_plan(run: Run, club_id: int) -> dict:
    club = db.one("SELECT * FROM clubs WHERE id = ?", (club_id,))
    bars = candidate_bars(club["city"], (club["team"],))
    if not bars:
        return {"error": f"No bar profiles in {club['city']} yet."}
    my_sched = get_schedule(run, club["team"])
    facts = []
    for bar in bars:
        conflicts = []
        bookings = db.query(
            "SELECT b.club_id, c.name, c.team FROM bookings b JOIN clubs c ON c.id = b.club_id "
            "WHERE b.bar_id = ? AND b.season = ? AND b.status = 'confirmed' AND b.club_id != ?",
            (bar["id"], config.CURRENT_SEASON, club_id),
        )
        for bk in bookings:
            conflicts += find_conflicts(my_sched, get_schedule(run, bk["team"]), bk["name"])
        turnout = club["typical_turnout"] or 0
        facts.append(
            {
                **_bar_facts(bar),
                "capacity_ok": (bar["capacity"] or 0) >= turnout,
                "in_preferred_area": (club["preferred_area"] or "").lower() in (bar["neighborhood"] or "").lower(),
                "other_clubs_booked": [bk["name"] for bk in bookings],
                "conflicts": conflicts,
            }
        )
    upcoming = [g.model_dump() for g in (my_sched.games if my_sched else [])][:6]
    prompt = (
        "Mode: season\n"
        f"Club: {json.dumps({k: club[k] for k in ('name', 'team', 'sport', 'city', 'typical_turnout', 'preferred_area')})}\n"
        + untrusted("CLUB NEEDS", club["needs"] or "", 800)
        + f"\nUpcoming games: {json.dumps(upcoming)}\n"
        + untrusted("CANDIDATE BARS (profile text written by bars)", json.dumps(facts, indent=1), 12000)
    )
    plan = run_agent(run, "matchmaker", prompt, SeasonPlan, effort="low")
    valid_ids = {f["bar_id"] for f in facts}
    plan.ranked = [r for r in plan.ranked if r.bar_id in valid_ids]
    if plan.recommended_bar_id not in valid_ids and plan.ranked:
        plan.recommended_bar_id = plan.ranked[0].bar_id
    run.add_step("Matchmaker", f"season plan for {club['name']}: {len(plan.ranked)} bars ranked, "
                 f"{sum(len(f['conflicts']) for f in facts)} schedule conflicts computed")
    return {"plan": plan.model_dump(), "facts": {f["bar_id"]: f for f in facts}, "club": club}


def find_rivalry_game(sched: TeamSchedule | None, rival_team: str) -> dict | None:
    if not sched:
        return None
    keys = [w for w in re.findall(r"[a-z]+", rival_team.lower()) if len(w) > 3] or [rival_team.lower()]
    for g in sched.games:
        if any(k in g.opponent.lower() for k in keys):
            return g.model_dump()
    return None


def rivalry_plan(run: Run, club_a_id: int, club_b_id: int) -> dict:
    a = db.one("SELECT * FROM clubs WHERE id = ?", (club_a_id,))
    b = db.one("SELECT * FROM clubs WHERE id = ?", (club_b_id,))
    sched_a = get_schedule(run, a["team"])
    game = find_rivalry_game(sched_a, b["team"])
    if game is None:
        sched_b = get_schedule(run, b["team"])
        game = find_rivalry_game(sched_b, a["team"])
    if game is None:
        return {"error": f"{a['team']} and {b['team']} don't play each other in the {config.CURRENT_SEASON} regular season schedule we found."}
    combined = (a["typical_turnout"] or 0) + (b["typical_turnout"] or 0)
    facts = []
    for bar in candidate_bars(a["city"], (a["team"], b["team"])):
        clash = db.query(
            "SELECT title FROM events WHERE bar_id = ? AND game LIKE ? AND status != 'cancelled'",
            (bar["id"], f"%{game['date']}%"),
        )
        facts.append(
            {
                **_bar_facts(bar),
                "holds_both_clubs": (bar["capacity"] or 0) >= combined,
                "is_home_bar_of": [c["name"] for c in (a, b) if c["home_bar_id"] == bar["id"]],
                "events_same_day": [c["title"] for c in clash],
            }
        )
    if not facts:
        return {"error": f"No bar profiles in {a['city']} yet."}
    prompt = (
        "Mode: rivalry\n"
        f"club_a: {json.dumps({k: a[k] for k in ('name', 'team', 'typical_turnout')})}\n"
        f"club_b: {json.dumps({k: b[k] for k in ('name', 'team', 'typical_turnout')})}\n"
        f"Combined turnout: {combined}\n"
        f"The game (from schedule): {json.dumps(game)}\nCity: {a['city']}\n"
        + untrusted("CANDIDATE BARS (profile text written by bars)", json.dumps(facts, indent=1), 12000)
    )
    plan = run_agent(run, "matchmaker", prompt, RivalryPlan, effort="low", max_output_tokens=5000)
    valid = {f["bar_id"]: f for f in facts}
    plan.ranked = [r for r in plan.ranked if r.bar_id in valid]
    fits = [r.bar_id for r in plan.ranked if valid[r.bar_id]["holds_both_clubs"]]
    if plan.recommended_bar_id not in valid or not valid[plan.recommended_bar_id]["holds_both_clubs"]:
        if fits:
            plan.recommended_bar_id = fits[0]
            plan.safety_notes.append("Recommendation changed by a code check: the first pick could not hold both clubs.")
    run.add_step("Matchmaker", f"rivalry plan {a['team']} vs {b['team']} on {game['date']}: "
                 f"{len(plan.ranked)} bars ranked for {combined} fans, {len(plan.drafts)} drafts written")
    return {"plan": plan.model_dump(), "facts": valid, "game": game, "club_a": a, "club_b": b, "combined": combined}
