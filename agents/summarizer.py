"""Game-Day Summarizer: turns a bar's posted reviews into a game-day score. Cached by review hash."""

from __future__ import annotations

import hashlib
import json

from agents.llm import run_agent, untrusted
from agents.schemas import GameDayScore
from core import db
from core.budget import Run


def summarize(run: Run, bar_id: int) -> dict | None:
    reviews = db.query(
        "SELECT id, team, rating, text FROM reviews WHERE bar_id = ? AND status = 'posted' ORDER BY id DESC LIMIT 25",
        (bar_id,),
    )
    if not reviews:
        return None
    digest = hashlib.sha1(json.dumps(reviews, sort_keys=True).encode()).hexdigest()
    cached = db.one("SELECT payload, reviews_hash FROM summaries WHERE bar_id = ?", (bar_id,))
    if cached and cached["reviews_hash"] == digest:
        run.add_step("Summarizer", f"bar {bar_id}: score from cache (no tokens)")
        return {**json.loads(cached["payload"]), "based_on": len(reviews), "cached": True}
    text = "\n".join(f"- [{r['rating']}/5, {r['team'] or 'fan'}] {r['text']}" for r in reviews)
    score = run_agent(run, "summarizer", untrusted("REVIEWS", text, 12000), GameDayScore, effort="none", max_output_tokens=800)
    payload = score.model_dump()
    db.execute(
        "INSERT OR REPLACE INTO summaries (bar_id, reviews_hash, payload, created_at) VALUES (?, ?, ?, ?)",
        (bar_id, digest, json.dumps(payload), db.now_iso()),
    )
    run.add_step("Summarizer", f"bar {bar_id}: game-day score {payload['overall']:.1f} from {len(reviews)} reviews")
    return {**payload, "based_on": len(reviews), "cached": False}
