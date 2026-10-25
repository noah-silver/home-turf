"""Verifier: code checks first, the model only for the cases code cannot settle (GUARDRAILS E6).

For each Scout candidate:
  1. geocode the address with Nominatim (the model never writes coordinates, S2),
  2. re-fetch the source page (public URLs only),
  3. check that the page names the bar, and mentions the current season near it.
Name + season found -> confirmed by code, no tokens spent. Everything else goes to the Verifier
agent in ONE batched call, with the page text wrapped as untrusted data.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

import config
from agents.llm import run_agent, untrusted
from agents.schemas import ScoutSpot, VerifierReport
from core.budget import Run
from tools.fetch_page import fetch_text
from tools.geocode import geocode

STOPWORDS = {"the", "bar", "pub", "grill", "tavern", "and", "restaurant", "sports", "saloon", "&", "co", "kitchen", "house"}
INJECTION_RE = re.compile(r"ignore (all |any )?(previous|prior|above) instructions|mark (this|it) as (confirmed|verified)|you are now", re.I)
SEASON_MARKERS = (str(config.CURRENT_SEASON), f"{config.CURRENT_SEASON - 1}-{str(config.CURRENT_SEASON)[2:]}")


def _name_tokens(name: str) -> list[str]:
    words = re.findall(r"[a-z0-9']+", name.lower())
    keep = [w for w in words if w not in STOPWORDS and len(w) > 1]
    return keep or words


def _find_name(text_lower: str, name: str) -> int:
    """Index of the bar's name in the page, or -1."""
    full = name.lower().strip()
    idx = text_lower.find(full)
    if idx >= 0:
        return idx
    tokens = _name_tokens(name)
    if tokens and all(t in text_lower for t in tokens):
        return text_lower.find(tokens[0])
    return -1


def _gather(spot: ScoutSpot, city: str) -> tuple[dict | None, dict]:
    """Address lookup and source re-check for one candidate (runs in a thread pool)."""
    geo = geocode(spot.address, city) if spot.address.lower() != "unknown" else None
    if geo is None:
        geo = geocode(f"{spot.bar_name}, {city}")
    return geo, fetch_text(spot.source_url)


def verify(run: Run, team: str, city: str, spots: list[ScoutSpot]) -> list[dict]:
    results: list[dict] = []
    ambiguous: list[tuple[int, str]] = []
    # Re-check every source at the same time (geocoding stays at 1 request/second inside its own lock).
    with ThreadPoolExecutor(max_workers=6) as pool:
        gathered = list(pool.map(lambda sp: _gather(sp, city), spots))
    for i, spot in enumerate(spots):
        geo, page = gathered[i]
        text = page["text"]
        lower = text.lower()
        name_at = _find_name(lower, spot.bar_name) if page["ok"] else -1
        window = lower[max(0, name_at - 1500): name_at + 1500] if name_at >= 0 else ""
        season_near = any(m in window for m in SEASON_MARKERS)
        injected = bool(INJECTION_RE.search(text))
        item = {
            **spot.model_dump(),
            "lat": geo["lat"] if geo else None,
            "lon": geo["lon"] if geo else None,
            "geocoded": geo is not None,
            "page_loaded": page["ok"],
            "page_error": page["error"],
            "name_on_page": name_at >= 0,
            "season_on_page": season_near,
            "injection_on_page": injected,
            "decided_by": "code",
            "status": None,
            "status_reason": "",
        }
        if page["ok"] and name_at >= 0 and season_near and not injected:
            item["status"] = "confirmed"
            item["status_reason"] = f"Source page names the bar and mentions the {config.CURRENT_SEASON} season."
        else:
            if page["ok"]:
                snippet = text[max(0, name_at - 1200): name_at + 1200] if name_at >= 0 else text[:2400]
                evidence = untrusted("SOURCE PAGE", snippet, 2600)
            else:
                evidence = f"(The source page could not be loaded: {page['error']}.)"
            ambiguous.append(
                (
                    i,
                    f"### Candidate {i}\nTeam: {getattr(spot, 'team', team)}\nBar: {spot.bar_name}\nAddress claimed: {spot.address}\n"
                    f"Club claimed: {spot.club_name}\nScout's quote: {spot.evidence_quote}\n"
                    f"Season claimed: {spot.season_seen}\nSource: {spot.source_url}\n"
                    f"Bar name found on page: {name_at >= 0}\n{evidence}",
                )
            )
        results.append(item)

    code_confirmed = sum(1 for r in results if r["status"] == "confirmed")
    if ambiguous:
        prompt = (
            f"Team: {team}\nCity: {city}\nCurrent season: {config.CURRENT_SEASON}\n\n"
            + "\n\n".join(block for _, block in ambiguous)
        )
        try:
            report = run_agent(run, "verifier", prompt, VerifierReport, effort="low", max_output_tokens=1500)
            verdicts = {v.index: v for v in report.verdicts}
        except Exception as exc:  # contained failure: fall back to cautious defaults
            verdicts = {}
            run.add_step("Verifier", f"model check failed ({exc}); marking as unverified")
        for i, _ in ambiguous:
            v = verdicts.get(i)
            results[i]["decided_by"] = "model"
            results[i]["status"] = v.status if v else "unverified"
            results[i]["status_reason"] = v.reason if v else "Could not be re-checked."

    for r in results:
        if r["injection_on_page"]:
            r["status"] = "rejected"
            r["status_reason"] = "Source page contains instructions aimed at AI systems; treated as unreliable."
        if not r["geocoded"] and r["status"] == "confirmed":
            r["status"] = "likely"
            r["status_reason"] += " The address could not be placed on the map."
    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("confirmed", "likely", "unverified", "rejected")}
    run.add_step(
        "Verifier",
        f"{code_confirmed} settled by free code checks, {len(ambiguous)} sent to the model; final: "
        + ", ".join(f"{k} {v}" for k, v in counts.items()),
    )
    return results
