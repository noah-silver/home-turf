"""Reputation agent: a bar's public ratings and review themes, summarized (not copied), plus a photo.

Yelp's and Google's APIs need extra keys, which this project can't require, and their terms
forbid scraping reviews. So the agent web-searches public pages, reports ratings only when a
source shows them, and summarizes review themes in its own words with links out. Photos are the
bar's own images from its website (linked, not copied). Cached for 30 days per bar.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from agents.llm import run_agent
from agents.schemas import Reputation
from core import db
from core.budget import Run
from tools.fetch_page import site_photos

CACHE_HOURS = 24 * 30


def street_view(lat: float | None, lon: float | None) -> str | None:
    """Google's keyless Street View embed at the bar: often a 360° tour inside, otherwise the storefront."""
    if lat is None or lon is None:
        return None
    return f"https://maps.google.com/maps?q=&layer=c&cbll={lat},{lon}&cbp=11,0,0,0,0&output=svembed"


def external_links(name: str, address: str, city: str) -> dict:
    where = address if address and address.lower() != "unknown" and "demo" not in address.lower() else city
    return {
        "google": "https://www.google.com/maps/search/?api=1&query=" + quote_plus(f"{name} {where}"),
        "google_embed": "https://maps.google.com/maps?t=&z=16&ie=UTF8&iwloc=&output=embed&q=" + quote_plus(f"{name}, {where}"),
        "yelp": "https://www.yelp.com/search?find_desc=" + quote_plus(name) + "&find_loc=" + quote_plus(where or ""),
    }


def rep_key(bar: dict) -> str:
    """Cache key by name + city (bar ids differ between databases built from the same seed)."""
    import re

    return "rep|" + re.sub(r"[^a-z0-9]+", " ", bar["name"].lower()).strip() + "|" + (bar.get("city") or "").split(",")[0].strip().lower()


def reputation(run: Run, bar: dict) -> dict | None:
    if bar.get("is_demo"):
        return None  # fictional demo venues have no public reviews
    key = rep_key(bar)
    cached = db.cache_get(key, CACHE_HOURS)
    if cached:
        run.add_step("Reputation", f"{bar['name']}: from cache (no tokens)")
        return {**cached, "cached": True}
    prompt = f"Bar: {bar['name']}\nAddress: {bar.get('address') or 'unknown'}\nCity: {bar.get('city') or ''}"
    rep = run_agent(run, "reputation", prompt, Reputation, tools=[{"type": "web_search"}], max_tool_calls=2, effort="low", max_output_tokens=2000)
    data = rep.model_dump()
    site = rep.official_site or bar.get("website") or ""
    data["photos"] = site_photos(site) if site else []
    db.cache_put(key, "reputation", data)
    run.add_step("Reputation", f"{bar['name']}: {len(rep.themes)} review themes, ratings G={rep.google_rating} Y={rep.yelp_rating}, {len(data['photos'])} photos from its website")
    return {**data, "cached": False}
