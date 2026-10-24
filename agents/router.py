"""Router agent: turns a fan's search into {intent, team, city}. No tools.

Identical searches are answered from a 30-day cache, so a repeat search costs zero tokens.
"""

from __future__ import annotations

import re

from agents.llm import run_agent, untrusted
from agents.schemas import Intent
from core import db
from core.budget import Run


def _key(query: str) -> str:
    return "route|" + re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()


def _describe(i: Intent) -> str:
    teams = i.team + (f" vs {i.team_b}" if i.team_b else "") if i.team else "?"
    return f"{i.intent}: {teams} in {i.city or '?'}"


def route(run: Run, query: str) -> Intent:
    cached = db.cache_get(_key(query), 24 * 30)
    if cached:
        intent = Intent(**cached)
        run.add_step("Router", f"{_describe(intent)} (cached, no tokens)")
        return intent
    intent = run_agent(run, "router", untrusted("SEARCH", query, 400), Intent, effort="none", max_output_tokens=600)
    if intent.intent in ("find", "rivalry"):
        db.cache_put(_key(query), "route", intent.model_dump())
    run.add_step("Router", _describe(intent))
    return intent
