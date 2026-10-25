"""Everything Home Turf knows about where fans watch in a city, grouped by bar.

Sources (no model calls): cached verified searches, fan suggestions, and Home Turf partner bars
with clubs booked for the season. Used by the map so a city view shows every team's logo.
"""

from __future__ import annotations

import json
import re

import config
from core import db

STATUS_ORDER = {"confirmed": 0, "partner": 1, "likely": 2, "suggested": 3, "unverified": 4, "allgames": 5}


def city_key(city: str | None) -> str:
    return (city or "").split(",")[0].strip().lower()


def _bar_key(name: str, city: str) -> str:
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return " ".join(w for w in words if w not in {"the", "bar", "pub"}) + "|" + city_key(city)


def _add(points: dict, *, name, address, lat, lon, bar_id, city, team, status, club, source_url="", sport=""):
    if lat is None or lon is None:
        return
    key = _bar_key(name, city)
    p = points.setdefault(key, {"bar_name": name, "address": address, "lat": lat, "lon": lon, "bar_id": bar_id, "city": city, "teams": []})
    if p["bar_id"] is None and bar_id:
        p["bar_id"] = bar_id
    for t in p["teams"]:
        if t["team"].lower() == team.lower():
            if STATUS_ORDER.get(status, 9) < STATUS_ORDER.get(t["status"], 9):
                t.update(status=status, club=club or t["club"])
            return
    p["teams"].append({"team": team, "status": status, "club": club or "", "source_url": source_url, "sport": sport})


def known_points(city: str | None = None) -> list[dict]:
    """All bars with fan-club links, optionally limited to one city (by city name)."""
    want = city_key(city) if city else None
    points: dict[str, dict] = {}
    for row in db.query("SELECT payload FROM cache WHERE kind = 'spots'"):
        payload = json.loads(row["payload"])
        if want and city_key(payload.get("city")) != want:
            continue
        for s in payload.get("spots", []):
            if s.get("status") == "rejected":
                continue
            _add(points, name=s["bar_name"], address=s.get("address", ""), lat=s.get("lat"), lon=s.get("lon"), bar_id=s.get("bar_id"),
                 city=payload["city"], team=payload["team"], status="allgames" if s.get("kind") == "allgames" else s["status"],
                 club=s.get("club_name") if s.get("club_name") != "unknown" else "", source_url=s.get("source_url", ""))
    for s in db.query("SELECT * FROM suggestions WHERE status != 'blocked'"):
        if want and city_key(s["city"]) != want:
            continue
        _add(points, name=s["bar_name"], address=s["address"], lat=s["lat"], lon=s["lon"], bar_id=s["bar_id"], city=s["city"],
             team=s["team"], status="confirmed" if s["status"] == "verified" else "suggested", club="", source_url=s["source_url"] or "")
    rows = db.query(
        "SELECT b.id bar_id, b.name, b.address, b.lat, b.lon, b.city, c.team, c.name club, c.sport FROM bookings k "
        "JOIN bars b ON b.id = k.bar_id JOIN clubs c ON c.id = k.club_id WHERE k.status = 'confirmed' AND k.season = ?",
        (config.CURRENT_SEASON,),
    )
    for r in rows:
        if want and city_key(r["city"]) != want:
            continue
        _add(points, name=r["name"], address=r["address"], lat=r["lat"], lon=r["lon"], bar_id=r["bar_id"], city=r["city"],
             team=r["team"], status="partner", club=r["club"], sport=r["sport"])
    out = list(points.values())
    for p in out:
        p["teams"].sort(key=lambda t: STATUS_ORDER.get(t["status"], 9))
    return out


def teams_in_city(city: str) -> list[dict]:
    """[{team, spots, best_status}] for the city overview list."""
    agg: dict[str, dict] = {}
    for p in known_points(city):
        for t in p["teams"]:
            a = agg.setdefault(t["team"], {"team": t["team"], "spots": 0, "best_status": t["status"]})
            a["spots"] += 1
            if STATUS_ORDER.get(t["status"], 9) < STATUS_ORDER.get(a["best_status"], 9):
                a["best_status"] = t["status"]
    return sorted(agg.values(), key=lambda a: (-a["spots"], a["team"]))
