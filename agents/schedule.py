"""Schedule agent: a team's season schedule via web search, cached for a day."""

from __future__ import annotations

import config
from agents.llm import run_agent
from agents.schemas import TeamSchedule
from core import db
from core.budget import Run


def cache_key(team: str) -> str:
    return f"schedule|{team.strip().lower()}|{config.CURRENT_SEASON}"


def get_schedule(run: Run, team: str) -> TeamSchedule | None:
    key = cache_key(team)
    cached = db.cache_get(key, config.SCHEDULE_CACHE_HOURS)
    if cached:
        run.add_step("Schedule", f"{team}: schedule from cache (no tokens)")
        return TeamSchedule(**cached)
    try:
        sched = run_agent(
            run,
            "schedule",
            f"Team: {team}\nSeason: {config.CURRENT_SEASON}\nList the regular-season schedule.",
            TeamSchedule,
            tools=[{"type": "web_search"}],
            max_tool_calls=2,
            effort="low",
            max_output_tokens=6000,
        )
    except Exception as exc:  # contained failure (GUARDRAILS S13)
        run.add_step("Schedule", f"{team}: schedule unavailable ({exc})")
        return None
    db.cache_put(key, "schedule", sched.model_dump())
    run.add_step("Schedule", f"{team}: {len(sched.games)} games found")
    return sched
