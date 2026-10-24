"""The pipeline that ties the agents together for each user action.

find_watch_spots:  Router -> (cache?) -> Scout -> Verifier -> save spots + unclaimed bar profiles
rivalry search:    Router -> find_watch_spots for both teams (max 2 scouts)
Each action is one Run with its own token cap; failures are contained and explained.
"""

from __future__ import annotations

import re
from typing import Any

import config
from agents.guard import code_screen
from agents.llm import AgentError
from agents.router import route
from agents.scout import scout
from agents.verifier import verify
from core import audit, db
from core.budget import BudgetExceeded, Run


def search_key(team: str, city: str) -> str:
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()  # noqa: E731
    return f"spots|{norm(team)}|{norm(city.split(',')[0])}"


def _link_bar(spot: dict, city: str) -> int | None:
    """Attach a found spot to a bar profile, creating an unclaimed profile if needed."""
    if spot["status"] == "rejected":
        return None
    first = spot["bar_name"].lower().split()[0] if spot["bar_name"] else ""
    for bar in db.query("SELECT id, name, city FROM bars"):
        if bar["name"].lower() == spot["bar_name"].lower() and (bar["city"] or "").split(",")[0].lower() == city.split(",")[0].lower():
            return bar["id"]
    if not first:
        return None
    return db.insert(
        "bars",
        {
            "name": spot["bar_name"],
            "address": spot["address"],
            "city": city,
            "neighborhood": "",
            "lat": spot["lat"],
            "lon": spot["lon"],
            "teams_hosted": spot.get("team", ""),
            "website": spot["source_url"] if spot.get("official_source") else "",
            "claimed": 0,
            "is_demo": 0,
            "source": "scout",
            "created_at": db.now_iso(),
        },
    )


STATUS_RANK = {"confirmed": 0, "likely": 1, "unverified": 2, "rejected": 3}


def _bar_key(name: str) -> str:
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return " ".join(w for w in words if w not in {"the", "chicago", "boston", "bar", "pub"}) or (name or "").lower()


def merge_duplicates(spots: list[dict]) -> list[dict]:
    """Same bar from several sources -> one spot with every source listed; best status wins."""
    merged: dict[str, dict] = {}
    for spot in spots:
        key = _bar_key(spot["bar_name"])
        source = {"url": spot["source_url"], "quote": spot["evidence_quote"], "status": spot["status"],
                  "official": spot.get("official_source", False), "reason": spot["status_reason"],
                  "page_loaded": spot.get("page_loaded", False), "name_on_page": spot.get("name_on_page", False),
                  "season_on_page": spot.get("season_on_page", False)}
        if key not in merged:
            merged[key] = {**spot, "sources": [source]}
            continue
        best = merged[key]
        best["sources"].append(source)
        if STATUS_RANK[spot["status"]] < STATUS_RANK[best["status"]]:
            keep_sources = best["sources"]
            merged[key] = {**spot, "sources": keep_sources}
            best = merged[key]
        if best["lat"] is None and spot["lat"] is not None:
            best.update(lat=spot["lat"], lon=spot["lon"], geocoded=True, address=spot["address"])
    out = list(merged.values())
    for spot in out:
        for flag in ("page_loaded", "name_on_page", "season_on_page"):
            spot[flag] = any(s.get(flag) for s in spot["sources"])
        live = [s for s in spot["sources"] if s["status"] != "rejected"]
        if spot["status"] == "likely" and len(live) >= 2 and any(s["official"] for s in live):
            spot["status"] = "confirmed"
            spot["status_reason"] = f"{len(live)} independent sources agree, including an official one."
            spot["decided_by"] = "code"
    return sorted(out, key=lambda s: STATUS_RANK[s["status"]])


def _spots_for(run: Run, team: str, city: str, sport: str | None) -> dict[str, Any]:
    key = search_key(team, city)
    cached = db.cache_get(key, config.SEARCH_CACHE_DAYS * 24)
    if cached:
        run.add_step("Cache", f"{team} in {city}: verified results from cache (no tokens, no web search)")
        audit.log("cache_hit", run_id=run.run_id, key=key)
        for spot in cached["spots"]:
            spot["bar_id"] = _link_bar(spot, city)
        return {**cached, "from_cache": True}
    audit.log("cache_miss", run_id=run.run_id, key=key)
    report = scout(run, team, city, sport)
    spots = merge_duplicates(verify(run, team, city, report.spots[:5])) if report.spots else []
    for spot in spots:
        spot["team"] = team
        spot["bar_id"] = _link_bar(spot, city)
    result = {
        "team": team,
        "city": city,
        "spots": spots,
        "club_name": report.club_name,
        "club_contact_url": report.club_contact_url,
        "search_notes": report.search_notes,
        "safety_notes": report.safety_notes,
        "found_at": db.now_iso(),
    }
    db.cache_put(key, "spots", result)
    for spot in spots:
        db.insert(
            "watch_spots",
            {
                "query_key": key, "team": team, "city": city, "club_name": spot["club_name"],
                "bar_name": spot["bar_name"], "address": spot["address"], "lat": spot["lat"],
                "lon": spot["lon"], "bar_id": spot.get("bar_id"), "source_url": spot["source_url"],
                "evidence_quote": spot["evidence_quote"], "season_seen": spot["season_seen"],
                "status": spot["status"], "status_reason": spot["status_reason"], "found_at": db.now_iso(),
            },
        )
    return {**result, "from_cache": False}


def find_watch_spots(query: str, session_id: str = "cli") -> dict[str, Any]:
    run = Run(kind="search", session_id=session_id)
    query = (query or "").strip()
    audit.log("search_start", run_id=run.run_id, session_id=session_id, query=query)
    if not query:
        return {"ok": False, "message": "Type a team and a city, like “USC fans in Chicago”.", "run": run}
    if len(query) > config.MAX_QUERY_CHARS:
        return {"ok": False, "message": f"Please keep searches under {config.MAX_QUERY_CHARS} characters.", "run": run}
    blocked = code_screen("review", query)  # same free injection filter as reviews
    if blocked and blocked["category"] == "injection":
        run.add_step("Guard", "search blocked by the free code filter: instruction-like text")
        audit.log("search_blocked", run_id=run.run_id, reason=blocked["reason"])
        return {"ok": False, "message": "That doesn't look like a search for a team and a city. Try “Bears fans in Boston”.", "run": run, "blocked": True}
    try:
        intent = route(run, query)
        if intent.intent in ("off_topic", "unsafe"):
            return {"ok": False, "message": intent.reply_if_rejected or "I can only help find where fans watch games.", "run": run, "blocked": intent.intent == "unsafe"}
        if not intent.city or not intent.team:
            missing = "city" if not intent.city else "team"
            return {"ok": False, "message": f"Which {missing}? Try “{intent.team or 'USC'} fans in {intent.city or 'Chicago'}”.", "run": run}
        groups = [_spots_for(run, intent.team, intent.city, intent.sport)]
        if intent.intent == "rivalry" and intent.team_b:
            groups.append(_spots_for(run, intent.team_b, intent.city, intent.sport))
        return {"ok": True, "intent": intent.model_dump(), "groups": groups, "run": run}
    except BudgetExceeded as exc:
        audit.log("budget_stop", run_id=run.run_id, message=str(exc))
        return {"ok": False, "message": str(exc), "run": run, "budget": True}
    except AgentError as exc:
        return {"ok": False, "message": f"Something went wrong on our side: {exc} Please try again.", "run": run}
