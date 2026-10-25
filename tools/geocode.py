"""Address -> coordinates with OpenStreetMap Nominatim (free, no key).

The model never writes coordinates (GUARDRAILS S2). Results are cached forever in SQLite, and
Nominatim's policy of at most one request per second is respected with a lock.
"""

from __future__ import annotations

import re
import threading
import time

import httpx

from core import db

URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "HomeTurf/1.0 (Yale SOM class project; fan-club watch party finder)"}
_LOCK = threading.Lock()
_last_call = [0.0]


def _normalize(address: str) -> str:
    return re.sub(r"\s+", " ", address or "").strip()


def geocode(address: str, city_hint: str = "") -> dict | None:
    """Return {'lat', 'lon', 'display'} or None if the address cannot be found."""
    address = _normalize(address)
    if not address or address.lower() == "unknown":
        return None
    has_place = bool(re.search(r",\s*[A-Z]{2}\b|\b\d{5}\b", address))
    if not city_hint or has_place or city_hint.split(",")[0].lower() in address.lower():
        query_text = address
    else:
        query_text = f"{address}, {city_hint}"
    cached = db.one("SELECT * FROM geocode_cache WHERE address = ?", (query_text,))
    if cached:
        return {"lat": cached["lat"], "lon": cached["lon"], "display": cached["display"]} if cached["ok"] else None

    result = None
    for attempt_text in _variants(query_text):
        result = _ask_nominatim(attempt_text)
        if result:
            break
    db.execute(
        "INSERT OR REPLACE INTO geocode_cache (address, lat, lon, display, ok, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            query_text,
            result["lat"] if result else None,
            result["lon"] if result else None,
            result["display"] if result else "",
            1 if result else 0,
            db.now_iso(),
        ),
    )
    return result


def _variants(text: str) -> list[str]:
    """Try the full address, then without suite/floor details and ZIP+4 noise."""
    variants = [text]
    simpler = re.sub(r"(?i)\b(suite|ste|unit|floor|fl|#)\s*[\w-]+,?", "", text)
    simpler = re.sub(r"\s+,", ",", simpler).strip(" ,")
    if simpler != text:
        variants.append(simpler)
    return variants


def _ask_nominatim(text: str) -> dict | None:
    with _LOCK:
        wait = 1.1 - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        try:
            resp = httpx.get(URL, params={"q": text, "format": "json", "limit": 1}, headers=HEADERS, timeout=10)
            _last_call[0] = time.time()
            resp.raise_for_status()
            rows = resp.json()
        except Exception:
            _last_call[0] = time.time()
            return None
    if not rows:
        return None
    row = rows[0]
    return {"lat": float(row["lat"]), "lon": float(row["lon"]), "display": row.get("display_name", "")}
