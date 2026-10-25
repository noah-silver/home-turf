"""Router agent: turns a fan's search into {intent, team, city}. No tools.

Identical searches are answered from a 30-day cache, so a repeat search costs zero tokens.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

import config
from agents.llm import run_agent, untrusted
from agents.schemas import Intent
from core import db
from core.budget import Run


def _key(query: str) -> str:
    return "route|" + re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()


def _describe(i: Intent) -> str:
    teams = i.team + (f" vs {i.team_b}" if i.team_b else "") if i.team else "?"
    return f"{i.intent}: {teams} in {i.city or '?'}"


SPORT_FOR_LEAGUE = {"NFL": "NFL", "college": "college football", "NBA": "NBA", "MLB": "MLB", "NHL": "NHL", "WNBA": "WNBA"}
FAN_WORDS = r"(?:fans?|fan club|fanclub|alumni|supporters|backers|club|bars?|watch(?:ing)?(?: party)?|people)"
PATTERN = re.compile(rf"^(?:where (?:do|are|can) )?(?P<team>.+?)\s+(?:{FAN_WORDS}\s+)*(?:watch\s+)?(?:in|near|around|at)\s+(?P<city>[a-z .'-]+?)\s*\??$", re.I)
RIVALRY = re.compile(r"^(?P<a>.+?)\s+(?:vs\.?|versus|v)\s+(?P<b>.+?)\s+(?:in|near)\s+(?P<city>[a-z .'-]+?)\s*\??$", re.I)


@lru_cache(maxsize=1)
def _cities() -> dict:
    path = config.DATA_DIR / "us_cities.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _city(text: str) -> str | None:
    return _cities().get(re.sub(r"\s+", " ", text.strip().lower().rstrip("?.")))


def fast_route(query: str) -> Intent | None:
    """Plain searches ("Bears fans in Boston", "Boston", "Harvard vs Yale in Chicago") are parsed
    with the team table and a city list, so they skip the Router model call. Anything else -> None."""
    from ui.team_logos import confident_match

    q = query.strip()
    city_only = _city(q) or _city(re.sub(r"^(?:fans?|fan clubs?|bars?|teams?)\s+(?:in|near)\s+", "", q, flags=re.I))
    if city_only:
        return Intent(intent="city", team=None, team_b=None, sport=None, city=city_only, reply_if_rejected=None)
    m = RIVALRY.match(q)
    if m and _city(m["city"]):
        a, b = confident_match(m["a"]), confident_match(m["b"])
        if a and b:
            return Intent(intent="rivalry", team=a["name"], team_b=b["name"], sport=SPORT_FOR_LEAGUE.get(a["league"], "soccer"),
                          city=_city(m["city"]), reply_if_rejected=None)
    m = PATTERN.match(q)
    if m and _city(m["city"]):
        t = confident_match(re.sub(rf"\s+{FAN_WORDS}$", "", m["team"].strip(), flags=re.I))
        if t:
            return Intent(intent="find", team=t["name"], team_b=None, sport=SPORT_FOR_LEAGUE.get(t["league"], "soccer"),
                          city=_city(m["city"]), reply_if_rejected=None)
    return None


def route(run: Run, query: str) -> Intent:
    fast = fast_route(query)
    if fast:
        run.add_step("Router", f"{_describe(fast)} (parsed instantly, no model call)")
        return fast
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
