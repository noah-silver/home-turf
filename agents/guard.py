"""Guard: screens reviews, bar profiles, and pitches before anything is posted (GUARDRAILS S4, S12).

Layer 1 is free code: length caps, known injection phrases, and personal contact details in
reviews. Layer 2 is the Guard agent for everything that passes layer 1. Every decision,
allowed or blocked, is written to guard_log and the audit trail.
"""

from __future__ import annotations

import re

import config
from agents.llm import run_agent, untrusted
from agents.schemas import GuardVerdict
from core import audit, db
from core.budget import Run

INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (your|all|the) (instructions|rules)",
    r"\bsystem prompt\b",
    r"^\s*(system|assistant)\s*:",
    r"you are now (a|an|the)\b",
    r"(rank|list|put|show) (this|our|my) (bar|venue|place) (first|#?1|at the top)",
    r"\b(always|must) (recommend|rank|choose) (this|our|us)\b",
    r"<\s*/?\s*(system|instructions?)\s*>",
]
PHONE_RE = re.compile(r"(?<!\d)(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
LIMITS = {"review": config.MAX_REVIEW_CHARS, "profile": config.MAX_PROFILE_FIELD_CHARS * 6, "pitch": 2000}


def _log(kind: str, layer: str, allowed: bool, category: str, reason: str, text: str) -> None:
    db.insert(
        "guard_log",
        {"ts": db.now_iso(), "kind": kind, "layer": layer, "allowed": int(allowed), "category": category, "reason": reason, "excerpt": text[:240]},
    )
    audit.log("guard_decision", kind=kind, layer=layer, allowed=allowed, category=category, reason=reason, excerpt=text[:240])


def code_screen(kind: str, text: str) -> dict | None:
    """Return a block decision, or None if the text passes the free checks."""
    stripped = (text or "").strip()
    if not stripped:
        return {"allow": False, "category": "spam", "reason": "Empty text."}
    if len(stripped) > LIMITS.get(kind, 2000):
        return {"allow": False, "category": "spam", "reason": f"Too long (limit {LIMITS.get(kind, 2000)} characters)."}
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, stripped, re.I | re.M):
            return {"allow": False, "category": "injection", "reason": "Contains instructions aimed at the AI or the rankings."}
    if kind == "review" and (PHONE_RE.search(stripped) or EMAIL_RE.search(stripped)):
        return {"allow": False, "category": "personal_info", "reason": "Reviews can't include phone numbers or email addresses."}
    return None


def screen(kind: str, text: str, context: str = "", session_id: str = "app") -> dict:
    """kind: 'review' | 'profile' | 'pitch'. Returns {allow, category, reason, layer}."""
    blocked = code_screen(kind, text)
    if blocked:
        _log(kind, "code", False, blocked["category"], blocked["reason"], text or "")
        return {**blocked, "layer": "code"}
    run = Run(kind=f"guard:{kind}", session_id=session_id)
    prompt = f"Content kind: {kind}\n"
    if context:
        prompt += f"Facts from the bar's own profile (for false_claim checks):\n{context}\n\n"
    prompt += untrusted("USER CONTENT", text, 3000)
    try:
        verdict = run_agent(run, "guard", prompt, GuardVerdict, effort="low", max_output_tokens=800)
        result = {**verdict.model_dump(), "layer": "model"}
    except Exception as exc:  # fail closed: hold the post rather than publish unchecked
        result = {"allow": False, "category": "spam", "reason": f"Could not be checked right now ({type(exc).__name__}). Please try again.", "layer": "error"}
    _log(kind, result["layer"], result["allow"], result["category"], result["reason"], text)
    return result
