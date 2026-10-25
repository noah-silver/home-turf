"""Scout agent: web-searches for where a team's fans or fan club watch games in a city."""

from __future__ import annotations

import config
from agents.llm import run_agent
from agents.schemas import ScoutReport
from core.budget import Run


def scout(
    run: Run,
    team: str,
    city: str,
    sport: str | None,
    *,
    effort: str = "low",
    max_searches: int = config.MAX_WEB_SEARCHES_PER_SCOUT,
    wide: bool = False,
    tried: str = "",
) -> ScoutReport:
    prompt = (
        f"Team: {team}\nSport: {sport or 'unknown'}\nCity: {city}\n"
        f"Current season: {config.CURRENT_SEASON}\n"
        "Find where this team's fans or official fan club watch games in this city."
    )
    if wide:
        prompt += f"\nWhat the first pass reported: {tried[:600]}"
    report = run_agent(
        run,
        "scout_wide" if wide else "scout",
        prompt,
        ScoutReport,
        tools=[{"type": "web_search"}],
        max_tool_calls=max_searches,
        effort=effort,
    )
    label = "Scout (wide pass)" if wide else "Scout"
    run.add_step(label, f"{len(report.spots)} candidate spots for {team} in {city}" + (" across the metro area" if wide else ""), notes=report.search_notes)
    return report
