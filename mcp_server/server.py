"""Home Turf MCP server: a second front door for AI assistants (Claude, ChatGPT, etc.).

A fan-club president can ask their own assistant "where do Bears fans watch in Boston?" or
"plan a Harvard-Yale party in Chicago" and get Home Turf's verified answers. The server
reuses the same agents, caches, spend caps, and audit trail as the web app.

Safety: every tool is read-only or returns drafts. Nothing here books a bar, sends a message,
approves an event, or edits a profile; those stay human-only actions in the web app.

Run (stdio):   .venv/bin/python mcp_server/server.py
Optional dependency:  pip install -r requirements-mcp.txt
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from agents.matchmaker import rivalry_plan  # noqa: E402
from core import db  # noqa: E402
from core import marketplace as mk  # noqa: E402
from core.budget import BudgetExceeded, Run  # noqa: E402
from core.orchestrator import find_watch_spots  # noqa: E402

# stdout carries the MCP protocol, so logs go to stderr (Lecture 9 rule).
logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
db.init_db()

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
server = MCPServer(
    name="home-turf",
    instructions="Find where a sports team's fans or fan club watch games in a city, look up bar profiles, "
    "and draft rivalry watch-party plans. Results are verified against sources; drafts are never sent.",
)


@server.tool(annotations=READ_ONLY)
def find_watch_spots_tool(query: str) -> str:
    """Find where a team's fans or official fan club watch games in a city.

    query: plain English, e.g. "USC fans in Chicago" or "Harvard vs Yale in Chicago".
    Returns verified spots with status (confirmed / likely / unverified), address, sources, and evidence quotes.
    """
    result = find_watch_spots(query[:300], session_id="mcp")
    totals = result["run"].totals()["total"]
    if not result["ok"]:
        return json.dumps({"ok": False, "message": result["message"]})
    groups = []
    for g in result["groups"]:
        groups.append({
            "team": g["team"], "city": g["city"], "official_club": g.get("club_name"), "club_page": g.get("club_contact_url"),
            "spots": [{"bar": s["bar_name"], "address": s["address"], "status": s["status"], "why": s["status_reason"],
                       "evidence": s["evidence_quote"], "sources": [x["url"] for x in s.get("sources", [])] or [s["source_url"]],
                       "home_turf_bar_id": s.get("bar_id")} for s in g["spots"] if s["status"] != "rejected"],
        })
    return json.dumps({"ok": True, "results": groups, "cost_usd": round(totals["cost"], 5), "from_cache": all(g.get("from_cache") for g in result["groups"])}, indent=1)


@server.tool(annotations=READ_ONLY)
def get_bar_profile(bar_id: int) -> str:
    """Look up a Home Turf bar profile (capacity, TVs, sound policy, specials) and its posted fan reviews."""
    b = mk.bar(bar_id)
    if not b:
        return json.dumps({"ok": False, "message": "No bar with that id."})
    keep = ("name", "address", "city", "neighborhood", "capacity", "tvs", "sound_policy", "specials", "teams_hosted", "claimed", "is_demo")
    reviews = [{"rating": r["rating"], "team": r["team"], "text": r["text"]} for r in mk.reviews_for(bar_id)[:10]]
    return json.dumps({"ok": True, "bar": {k: b[k] for k in keep}, "reviews": reviews}, indent=1)


@server.tool(annotations=READ_ONLY)
def list_fan_clubs(city: str) -> str:
    """List fan clubs on Home Turf in a city (e.g. "Chicago, IL"), with team, typical turnout, and season home bar."""
    clubs = mk.clubs_in_city(city)
    out = [{"club_id": c["id"], "name": c["name"], "team": c["team"], "typical_turnout": c["typical_turnout"],
            "home_bar": (mk.bar(c["home_bar_id"]) or {}).get("name") if c["home_bar_id"] else None} for c in clubs]
    return json.dumps({"city": city, "clubs": out}, indent=1)


@server.tool(annotations=READ_ONLY)
def draft_rivalry_watch_party(club_a_id: int, club_b_id: int) -> str:
    """Draft (but do not send or book) a joint rivalry watch party for two clubs in the same city.

    Returns the game, ranked bars that hold both crowds, logistics, and three draft invitations.
    The presidents and the bar must approve inside the Home Turf web app before anything happens.
    """
    run = Run(kind="rivalry_match", session_id="mcp")
    try:
        out = rivalry_plan(run, club_a_id, club_b_id)
    except BudgetExceeded as exc:
        return json.dumps({"ok": False, "message": str(exc)})
    if "error" in out:
        return json.dumps({"ok": False, "message": out["error"]})
    plan = out["plan"]
    return json.dumps({"ok": True, "status": "draft_not_sent", "game": out["game"], "combined_turnout": out["combined"],
                       "recommended_bar": (mk.bar(plan["recommended_bar_id"]) or {}).get("name"), "plan": plan,
                       "cost_usd": round(run.totals()["total"]["cost"], 5)}, indent=1)


if __name__ == "__main__":
    server.run("stdio")
