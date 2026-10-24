"""Pitch Writer: a bar's pitch to a fan club, grounded only in the bar's own profile (GUARDRAILS S5).

After the model writes the pitch, a code validator pulls every number out of it and checks that
each one appears in the facts we gave the model. Any number that does not is an invented
promise ("$3 beers", "20 TVs"): the model gets one retry with the problem named, and if it
still invents, the pitch is returned with a warning and cannot be sent until edited.
"""

from __future__ import annotations

import json
import re

from agents.llm import run_agent, untrusted
from agents.schedule import get_schedule
from agents.schemas import Pitch
from core import db
from core.budget import Run

NUMBER_RE = re.compile(r"\$?\d+(?:[.,:]\d+)?%?")
BAR_FACT_FIELDS = ("name", "neighborhood", "capacity", "tvs", "sound_policy", "specials", "pitch_line", "teams_hosted")
CLUB_FACT_FIELDS = ("name", "team", "city", "typical_turnout", "preferred_area")


def numbers_in(text: str) -> set[str]:
    """Numbers in text; prices keep their "$" so "$1" never matches a plain "1"."""
    out = set()
    for raw in NUMBER_RE.findall(text or ""):
        n = raw.strip("$%").replace(",", "").rstrip(".")
        out.add("$" + n if raw.startswith("$") else n)
    return out


def invented_numbers(body: str, allowed_text: str) -> list[str]:
    allowed = numbers_in(allowed_text)
    plain_allowed = {a.lstrip("$") for a in allowed}
    bad = []
    for n in sorted(numbers_in(body)):
        if n in allowed:
            continue
        if not n.startswith("$") and (n in plain_allowed or (":" in n and n.split(":")[0] in plain_allowed)):
            continue
        bad.append(n)
    return bad


def facts_text(bar: dict, club: dict, games: list[dict]) -> str:
    """Only the facts a pitch may quote: no ids, flags, or coordinates."""
    return (json.dumps({k: bar[k] for k in BAR_FACT_FIELDS}) + json.dumps({k: club[k] for k in CLUB_FACT_FIELDS})
            + json.dumps(games))


def write_pitch(run: Run, bar_id: int, club_id: int) -> dict:
    bar = db.one("SELECT * FROM bars WHERE id = ?", (bar_id,))
    club = db.one("SELECT * FROM clubs WHERE id = ?", (club_id,))
    sched = get_schedule(run, club["team"])
    games = [g.model_dump() for g in (sched.games if sched else [])][:4]
    bar_profile = {k: bar[k] for k in BAR_FACT_FIELDS}
    club_profile = {k: club[k] for k in CLUB_FACT_FIELDS}
    allowed = facts_text(bar, club, games)
    prompt = (
        untrusted("BAR PROFILE", json.dumps(bar_profile, indent=1), 3000)
        + "\n"
        + f"CLUB PROFILE: {json.dumps(club_profile)}\n"
        + f"Upcoming games (schedule facts): {json.dumps(games)}\n"
    )
    pitch = run_agent(run, "pitch_writer", prompt, Pitch, effort="low", max_output_tokens=1500)
    bad = invented_numbers(pitch.body + " " + pitch.subject, allowed)
    retried = False
    if bad:
        retried = True
        run.add_step("Pitch Writer", f"validator caught invented numbers {bad}; retrying once")
        pitch = run_agent(
            run,
            "pitch_writer",
            prompt + f"\nYour previous draft used numbers not in the bar profile: {bad}. Rewrite without them.",
            Pitch,
            effort="low",
            max_output_tokens=1500,
        )
        bad = invented_numbers(pitch.body + " " + pitch.subject, allowed)
    run.add_step("Pitch Writer", f"pitch for {club['name']} drafted" + (f"; still unsupported: {bad}" if bad else "; all numbers grounded"))
    return {"pitch": pitch.model_dump(), "unsupported_numbers": bad, "retried": retried}
