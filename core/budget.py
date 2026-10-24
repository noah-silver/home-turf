"""Runs and spend caps (GUARDRAILS E2, E3).

A Run is one user action (a search, a matchmaking run, a pitch). Every model call is charged
to a Run. Before each call we check three caps: this run, this browser session, and the whole
app today. When a cap is hit the call never happens and the user gets a clear message.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import config
from core import db


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Run:
    kind: str
    session_id: str = "cli"
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    tokens: int = 0
    cost: float = 0.0
    web_searches: int = 0
    steps: list[dict[str, Any]] = field(default_factory=list)
    token_cap: int = config.MAX_TOKENS_PER_RUN

    def add_step(self, agent: str, summary: str, **extra: Any) -> None:
        self.steps.append({"agent": agent, "summary": summary, **extra})

    def totals(self) -> dict[str, Any]:
        rows = db.query(
            "SELECT agent, SUM(input_tokens) i, SUM(cached_tokens) c, SUM(output_tokens) o, "
            "SUM(reasoning_tokens) r, SUM(web_searches) w, SUM(cost_usd) usd, SUM(latency_ms) ms, "
            "COUNT(*) calls FROM usage WHERE run_id = ? GROUP BY agent ORDER BY MIN(id)",
            (self.run_id,),
        )
        total = {
            "input": sum(r["i"] or 0 for r in rows),
            "cached": sum(r["c"] or 0 for r in rows),
            "output": sum(r["o"] or 0 for r in rows),
            "reasoning": sum(r["r"] or 0 for r in rows),
            "web_searches": sum(r["w"] or 0 for r in rows),
            "cost": sum(r["usd"] or 0 for r in rows),
            "calls": sum(r["calls"] or 0 for r in rows),
        }
        return {"run_id": self.run_id, "by_agent": rows, "total": total}


def session_tokens(session_id: str) -> int:
    row = db.one(
        "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) t FROM usage WHERE session_id = ?",
        (session_id,),
    )
    return int(row["t"]) if row else 0


def day_tokens() -> int:
    row = db.one(
        "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) t FROM usage WHERE day = ?",
        (db.today(),),
    )
    return int(row["t"]) if row else 0


def check(run: Run) -> None:
    if run.tokens >= run.token_cap:
        raise BudgetExceeded(
            f"This request hit its {run.token_cap:,}-token limit, so it was stopped to protect the budget."
        )
    if session_tokens(run.session_id) >= config.MAX_TOKENS_PER_SESSION:
        raise BudgetExceeded("You've reached this session's AI budget. Please try again later.")
    if day_tokens() >= config.MAX_TOKENS_PER_DAY:
        raise BudgetExceeded("Home Turf has reached today's AI budget. Cached results still work.")
