"""The pipeline that ties the agents together for each user action.

find_watch_spots:  Router -> (cache?) -> Scout -> Verifier -> save spots + unclaimed bar profiles
rivalry search:    Router -> find_watch_spots for both teams (max 2 scouts)
Each action is one Run with its own token cap; failures are contained and explained.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
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


def _wide_pass(run: Run, team: str, city: str, sport: str | None, spots: list[dict], report):
    """Second, wider Scout pass: metro area, fan club directories, plus verified every-game bars."""
    wide = scout(run, team, city, sport, wide=True, max_searches=config.MAX_WEB_SEARCHES_WIDE, tried=report.search_notes)
    if wide.spots:
        seen = {s["bar_name"].lower() for s in spots}
        fresh = [w for w in wide.spots if w.bar_name.lower() not in seen][:5]
        spots = merge_duplicates(spots + verify(run, team, city, fresh)) if fresh else spots
    allgames: list[dict] = []
    if wide.allgames_spots:
        allgames = [a for a in merge_duplicates(verify(run, team, city, wide.allgames_spots[:3])) if a["status"] != "rejected"]
        for a in allgames:
            a["kind"] = "allgames"
    report.search_notes = wide.search_notes or report.search_notes
    report.club_name = report.club_name or wide.club_name
    report.club_contact_url = report.club_contact_url or wide.club_contact_url
    return spots, allgames, report


def widen_search(team: str, city: str, sport: str | None, session_id: str) -> dict[str, Any]:
    """User clicked "Search wider": run the wide pass and merge it into the cached result."""
    run = Run(kind="search_wider", session_id=session_id)
    key = search_key(team, city)
    cached = db.cache_get(key, config.SEARCH_CACHE_DAYS * 24) or {"team": team, "sport": sport or "", "city": city, "spots": [], "allgames": []}

    class _Notes:  # the wide pass only needs these fields from the first report
        search_notes = cached.get("search_notes") or ""
        club_name = cached.get("club_name")
        club_contact_url = cached.get("club_contact_url")
        safety_notes: list = []

    try:
        spots, allgames, notes = _wide_pass(run, team, city, sport, cached.get("spots", []), _Notes())
    except (BudgetExceeded, AgentError) as exc:
        return {"ok": False, "message": str(exc), "run": run}
    for spot in spots + allgames:
        spot["team"] = team
        spot["bar_id"] = _link_bar(spot, city)
    cached.update(spots=spots, allgames=allgames, wide_done=True, search_notes=notes.search_notes,
                  club_name=notes.club_name, club_contact_url=notes.club_contact_url, found_at=db.now_iso())
    db.cache_put(key, "spots", cached)
    return {"ok": True, "group": {**cached, "from_cache": False}, "run": run}


def _spots_for(run: Run, team: str, city: str, sport: str | None) -> dict[str, Any]:
    key = search_key(team, city)
    cached = db.cache_get(key, config.SEARCH_CACHE_DAYS * 24)
    if cached and not cached.get("spots") and not cached.get("allgames"):
        cached = db.cache_get(key, config.EMPTY_RESULT_CACHE_HOURS)  # retry empty results sooner
    if cached:
        run.add_step("Cache", f"{team} in {city}: verified results from cache (no tokens, no web search)")
        audit.log("cache_hit", run_id=run.run_id, key=key)
        for spot in cached["spots"]:
            spot["bar_id"] = _link_bar(spot, city)
        return {**cached, "from_cache": True}
    audit.log("cache_miss", run_id=run.run_id, key=key)
    report = scout(run, team, city, sport)
    spots = merge_duplicates(verify(run, team, city, report.spots[:5])) if report.spots else []
    allgames: list[dict] = []
    wide_done = False
    if not any(s["status"] != "rejected" for s in spots):
        # Nothing at all: escalate automatically (the Falcons-in-Phoenix case).
        spots, allgames, report = _wide_pass(run, team, city, sport, spots, report)
        wide_done = True
    for spot in spots + allgames:
        spot["team"] = team
        spot["bar_id"] = _link_bar(spot, city)
    result = {
        "team": team,
        "sport": sport or "",
        "city": city,
        "spots": spots,
        "allgames": allgames,
        "wide_done": wide_done,
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
        if intent.intent == "city" and intent.city:
            run.add_step("City view", f"every team with a known fan spot in {intent.city} (no extra tokens)")
            return {"ok": True, "intent": intent.model_dump(), "groups": [], "city": intent.city, "run": run}
        if not intent.city or not intent.team:
            missing = "city" if not intent.city else "team"
            return {"ok": False, "message": f"Which {missing}? Try “{intent.team or 'USC'} fans in {intent.city or 'Chicago'}”.", "run": run}
        teams = [intent.team] + ([intent.team_b] if intent.intent == "rivalry" and intent.team_b else [])
        with ThreadPoolExecutor(max_workers=2) as pool:  # rivalry: both teams at once
            groups = list(pool.map(lambda t: _spots_for(run, t, intent.city, intent.sport), teams))
        return {"ok": True, "intent": intent.model_dump(), "groups": groups, "city": intent.city, "run": run}
    except BudgetExceeded as exc:
        audit.log("budget_stop", run_id=run.run_id, message=str(exc))
        return {"ok": False, "message": str(exc), "run": run, "budget": True}
    except AgentError as exc:
        return {"ok": False, "message": f"Something went wrong on our side: {exc} Please try again.", "run": run}
