"""Scout agent: web-searches for where a team's fans or fan club watch games in a city."""

from __future__ import annotations

import config
from agents.llm import run_agent
from agents.schemas import ScoutReport
from core.budget import Run


def scout(run: Run, team: str, city: str, sport: str | None, *, effort: str = "low", max_searches: int = config.MAX_WEB_SEARCHES_PER_SCOUT) -> ScoutReport:
    prompt = (
        f"Team: {team}\nSport: {sport or 'unknown'}\nCity: {city}\n"
        f"Current season: {config.CURRENT_SEASON}\n"
        "Find where this team's fans or official fan club watch games in this city."
    )
    report = run_agent(
        run,
        "scout",
        prompt,
        ScoutReport,
        tools=[{"type": "web_search"}],
        max_tool_calls=max_searches,
        effort=effort,
    )
    run.add_step("Scout", f"{len(report.spots)} candidate spots for {team} in {city}", notes=report.search_notes)
    return report
