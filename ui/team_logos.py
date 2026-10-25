"""Team name -> logo, colors, and abbreviation (from data/team_logos.json, built by scripts/build_team_logos.py)."""

from __future__ import annotations

import json
import re
from functools import lru_cache

import config

COLLEGE_HINTS = ("college", "ncaa", "university")
SOCCER = {"MLS", "EPL", "EFL", "LaLiga", "Bundesliga", "SerieA", "Ligue1", "SPFL", "LigaMX"}
LEAGUE_ORDER = ["NFL", "NCAA", "MLB", "NBA", "NHL", "Soccer", "WNBA", "Other"]


def league_label(league: str) -> str:
    """Filter group for a league code: NFL, NCAA, MLB, NBA, NHL, Soccer, WNBA, or Other."""
    if league == "college":
        return "NCAA"
    if league in SOCCER:
        return "Soccer"
    return league if league in LEAGUE_ORDER else "Other"


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower().replace("&", "and"))


@lru_cache(maxsize=1)
def _teams() -> list[dict]:
    path = config.DATA_DIR / "team_logos.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


@lru_cache(maxsize=2048)
def confident_match(text: str) -> dict | None:
    """Exact-or-near match only (used to skip the Router model call for plain searches)."""
    want = _tokens(text)
    if not want:
        return None
    best, best_score = None, 0.0
    for t in _teams():
        for name in (t["name"], f"{t['location']} {t['nickname']}", t["short"], t["nickname"], t["location"]):
            have = _tokens(name)
            if not have:
                continue
            if have == want:
                score = 100 if name in (t["name"], f"{t['location']} {t['nickname']}") else 70
            else:
                continue
            if score > best_score:
                best, best_score = t, score
    ambiguous = sum(1 for t in _teams() if want in (_tokens(t["nickname"]), _tokens(t["location"]), _tokens(t["short"]))) > 1
    if best is None or (best_score < 100 and ambiguous):
        return None
    return best


@lru_cache(maxsize=2048)
def lookup(team: str, sport: str = "") -> dict:
    """Best match for a team name. Always returns a dict with logo (or None), color, abbr, name."""
    want = _tokens(team)
    fallback = {"name": team, "logo": None, "color": "#0f2240", "alt_color": "#b8902f",
                "abbr": "".join(w[0] for w in want[:3]).upper() or "?", "league": ""}
    if not want:
        return fallback
    prefer_college = any(h in (sport or "").lower() for h in COLLEGE_HINTS)
    best, best_score = None, 0.0
    for t in _teams():
        names = [t["name"], f"{t['location']} {t['nickname']}", t["short"]]
        for name in names:
            have = _tokens(name)
            if not have:
                continue
            if have == want:
                score = 100.0
            else:
                overlap = len(set(want) & set(have))
                if overlap == 0:
                    continue
                score = 60 * overlap / max(len(set(want)), len(set(have)))
                if set(have) <= set(want) or set(want) <= set(have):
                    score += 20
            if prefer_college and t["league"] == "college":
                score += 5
            if not prefer_college and sport and (t["league"].lower() in sport.lower() or ("soccer" in sport.lower() and t["league"] in SOCCER)):
                score += 5
            if score > best_score:
                best, best_score = t, score
    if best is None or best_score < 45:
        return {**fallback, "group": "Other"}
    return {**best, "group": league_label(best["league"])}
