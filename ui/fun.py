"""Game-day touches: the live ticker, the team-logo wall, floating hero logos, and a football spinner."""

from __future__ import annotations

import json
import random

from dash import dcc, html

from core import db
from core.citymap import known_points
from ui.components import search_href
from ui.team_logos import LEAGUE_ORDER, lookup


def ticker() -> html.Div:
    """ESPN-style bottom line built from real Home Turf activity (no model calls)."""
    items: list[str] = []
    for row in db.query("SELECT payload FROM cache WHERE kind = 'spots' ORDER BY created_at DESC LIMIT 40"):
        p = json.loads(row["payload"])
        good = [s for s in p.get("spots", []) if s.get("status") in ("confirmed", "likely")]
        if good:
            items.append(f"📍 {p['team']} fans → {good[0]['bar_name']}, {p['city'].split(',')[0]}")
    import config

    for e in [] if config.REAL_ONLY else db.query("SELECT title, status FROM events ORDER BY id DESC LIMIT 5"):
        items.append(("🎉 CONFIRMED: " if e["status"] == "confirmed" else "🤝 Proposed: ") + e["title"])
    review_sql = ("SELECT b.name, r.rating, r.team FROM reviews r JOIN bars b ON b.id = r.bar_id WHERE r.status = 'posted'"
                  + (" AND r.is_seed = 0 AND b.is_demo = 0" if config.REAL_ONLY else "") + " ORDER BY r.id DESC LIMIT 5")
    for r in db.query(review_sql):
        items.append(f"⭐ {r['rating']}/5 for {r['name']}" + (f" from a {r['team']} fan" if r["team"] else ""))
    items = items or ["🏈 Search any team and city to find your people on game day"]
    random.Random(len(items)).shuffle(items)
    track = [html.Span(t, className="tick") for t in items]
    return html.Div(className="ticker", children=[
        html.Div("LIVE", className="ticker-tag"),
        html.Div(className="ticker-window", children=html.Div(track + track, className="ticker-track",
                                                              style={"animationDuration": f"{max(30, 6 * len(items))}s"})),
    ])


def mapped_teams(limit: int = 60) -> list[dict]:
    """Every team with a known fan spot, with the cities where it has one."""
    teams: dict[str, set] = {}
    for p in known_points():
        for t in p["teams"]:
            teams.setdefault(t["team"], set()).add(p["city"].split(",")[0])
    out = [{"team": t, "cities": sorted(c), "info": lookup(t)} for t, c in teams.items()]
    # Interleave leagues (NFL, NCAA, MLB, ...) so no single league dominates the wall.
    out.sort(key=lambda x: (x["info"]["logo"] is None, -len(x["cities"]), x["team"]))
    buckets: dict[str, list] = {}
    for t in out:
        buckets.setdefault(t["info"].get("group", "Other"), []).append(t)
    order = [g for g in LEAGUE_ORDER if g in buckets]
    mixed = []
    while any(buckets.get(g) for g in order):
        for g in order:
            if buckets.get(g):
                mixed.append(buckets[g].pop(0))
    return mixed[:limit]


def logo_wall() -> html.Div:
    tiles = []
    for t in mapped_teams():
        info = t["info"]
        city = t["cities"][0]
        inner = html.Img(src=info["logo"], alt=t["team"]) if info["logo"] else html.Span(info["abbr"], className="mono", style={"background": info["color"]})
        tiles.append(dcc.Link(href=search_href(f"{t['team']} fans in {city}"), className="logo-tile", title=f"{t['team']}: {', '.join(t['cities'])}",
                              children=[inner, html.Div(t["team"], className="lt-name"), html.Div(" · ".join(t["cities"][:2]), className="lt-city")]))
    return html.Div(tiles, className="logo-wall")


def floating_logos(n: int = 9) -> html.Div:
    teams = [t for t in mapped_teams() if t["info"]["logo"]][:n]
    spots = [(80, 10), (91, 26), (73, 34), (86, 50), (75, 64), (92, 72), (68, 84), (84, 86), (66, 12)]
    return html.Div(className="floaters", children=[
        html.Img(src=t["info"]["logo"], className="floater", style={"left": f"{x}%", "top": f"{y}%", "animationDelay": f"{i * 0.7:.1f}s"})
        for i, (t, (x, y)) in enumerate(zip(teams, spots))
    ])


def football_spinner() -> html.Div:
    return html.Div(className="football-spin", children=[html.Span("🏈"), html.Div("Huddling with the agents…", className="tiny")])
