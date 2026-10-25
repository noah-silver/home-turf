"""Find a watch spot: search box, verified results, a city map of team logos, and a run receipt."""

from __future__ import annotations

import time
from urllib.parse import parse_qs

from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from core import marketplace as mk
from core.citymap import known_points, teams_in_city
from core.orchestrator import find_watch_spots
from ui.fun import football_spinner
from ui.components import empty_state, notice, receipt, search_href, spot_card
from ui.logo_map import iframe_style, map_src
from ui.team_logos import LEAGUE_ORDER, lookup

CHIPS = ["Yale fans in Chicago", "Yale fans in New York", "Yale vs Princeton in New York", "Patriots fans in New York", "New Haven", "Boston", "New York"]


def team_badge(team: str, sport: str = "", size: int = 34) -> html.Span:
    t = lookup(team, sport)
    if t["logo"]:
        return html.Img(src=t["logo"], alt=team, className="team-logo", style={"width": f"{size}px", "height": f"{size}px"})
    return html.Span(t["abbr"], className="team-mono", style={"width": f"{size}px", "height": f"{size}px", "lineHeight": f"{size}px", "background": t["color"]})


def layout(search: str = "") -> html.Div:
    q = parse_qs((search or "").lstrip("?")).get("q", [""])[0]
    return html.Div(
        className="page",
        children=[
            dcc.Store(id="find-autorun", data=q),
            dcc.Store(id="find-context"),
            html.Div(
                className="find-layout",
                children=[
                    html.Div([
                        html.Div("Find a watch spot", className="eyebrow"),
                        html.H2("Where do your fans watch?"),
                        html.Div(className="searchbar", children=[
                            dcc.Input(id="find-q", type="text", value=q, placeholder="Team + city (“USC fans in Chicago”) or just a city (“Boston”)", n_submit=0, maxLength=300),
                            html.Button("Search", id="find-go", className="btn btn-gold"),
                        ]),
                        html.Div([dcc.Link(c, href=search_href(c), className="chip light") for c in CHIPS], className="chips"),
                        dcc.Loading(
                            custom_spinner=football_spinner(), overlay_style={"visibility": "visible", "opacity": 0.35},
                            children=html.Div(id="find-results", className="results", children=empty_state(
                                "🏟️", "Search a team and a city, or just a city",
                                "Every pin on the map is a team logo. We check each spot against its source before it shows up. New searches take a few seconds; popular ones load instantly.")),
                        ),
                    ]),
                    html.Div(className="card map-card", children=html.Iframe(id="find-map", src=map_src(known_points(), title="Every fan spot Home Turf knows"), style=iframe_style())),
                ],
            ),
        ],
    )


def _suggest_form(team: str, city: str) -> html.Details:
    return html.Details(className="suggest", children=[
        html.Summary(f"Know where {team or 'your team'} fans watch in {city.split(',')[0] if city else 'this city'}? Add it"),
        html.Div(className="grid-2", style={"gap": "8px", "marginTop": "8px"}, children=[
            dcc.Input(id="sug-bar", type="text", placeholder="Bar name", maxLength=120),
            dcc.Input(id="sug-address", type="text", placeholder="Street address (optional)", maxLength=200),
            dcc.Input(id="sug-team", type="text", value=team, placeholder="Team", maxLength=80),
            dcc.Input(id="sug-city", type="text", value=city, placeholder="City", maxLength=80),
        ]),
        dcc.Input(id="sug-url", type="text", placeholder="Link that shows it (club page, bar site, article) — lets us verify it", maxLength=300, style={"marginTop": "8px"}),
        html.Div(className="row", style={"marginTop": "8px"}, children=[
            html.Button("Add this spot", id="sug-go", className="btn btn-navy btn-sm"),
            html.Span("We check new spots before they appear. A link helps us verify it.", className="tiny muted"),
        ]),
        dcc.Loading(html.Div(id="sug-msg"), type="dot", color="#b8902f"),
    ])


def _suggestion_card(s: dict) -> html.Div:
    verified = s["status"] == "verified"
    return html.Div(className=f"spot {'confirmed' if verified else 'suggested'}", children=[
        html.Div(className="row", children=[html.H4(s["bar_name"]), html.Div(className="spacer"),
                                            html.Span("Verified (fan link)" if verified else "Fan-suggested", className="badge confirmed" if verified else "badge suggested")]),
        html.Div(s["address"] or "Address not given", className="small muted"),
        html.Div(s["verify_reason"], className="tiny muted", style={"marginTop": "6px"}),
        html.A("Source", href=s["source_url"], target="_blank", className="small") if s["source_url"] else None,
    ])


def _city_overview(city: str) -> list:
    from agents.city_sweep import recently_swept

    short = city.split(",")[0]
    teams = teams_in_city(city)
    head = html.Div(className="group-head", children=[html.H3(f"Fans watching in {city}"),
                    html.Div(f"{len(teams)} team(s) with known spots · use the league buttons on the map to filter", className="tiny", style={"color": "#9fb0cc", "marginTop": "4px"})])
    sweep = html.Div(className="suggest", children=[
        html.Div(className="row", children=[
            html.Div([html.B(f"Map every team's fans in {short}"),
                      html.Div("We'll scan city-wide guides (a bar for every NFL team, alumni watch parties, supporters' clubs), "
                               "check each bar, and add them to the map. Takes about a minute or two.", className="tiny muted")], style={"flex": 1}),
            html.Button("Map this city", id="sweep-go", className="btn btn-gold btn-sm"),
        ]),
        dcc.Store(id="sweep-city", data=city),
        dcc.Loading(html.Div(id="sweep-msg"), custom_spinner=football_spinner()),
    ]) if not recently_swept(city) or len(teams) < 5 else None
    if not teams:
        return [head, notice("info", f"No fan spots on file for {city} yet."), sweep]
    groups: dict[str, list] = {}
    for t in teams:
        groups.setdefault(lookup(t["team"])["group"], []).append(t)
    blocks = [head, sweep]
    for g in LEAGUE_ORDER:
        if g not in groups:
            continue
        blocks.append(html.Div(f"{g} · {len(groups[g])}", className="section-sub"))
        blocks.append(html.Div([dcc.Link(href=search_href(f"{t['team']} fans in {short}"), className="team-row", children=[
            team_badge(t["team"]), html.Div([html.B(t["team"]), html.Div(f"{t['spots']} spot(s) · best: {t['best_status']}", className="tiny muted")]),
            html.Span("→", className="spacer", style={"textAlign": "right", "color": "#b8902f", "fontWeight": 700})]) for t in groups[g]], className="team-list"))
    return blocks


@callback(
    Output("find-results", "children"),
    Output("find-map", "src"),
    Input("find-go", "n_clicks"),
    Input("find-q", "n_submit"),
    Input("find-autorun", "data"),
    State("find-q", "value"),
    State("session", "data"),
    prevent_initial_call=False,
    running=[(Output("find-go", "disabled"), True, False)],
)
def run_search(_clicks, _submit, autorun, value, session):
    query = (value or autorun or "").strip()
    if not query:
        return no_update, no_update
    sid = (session or {}).get("sid", "anon")
    started = time.perf_counter()
    result = find_watch_spots(query, session_id=sid)
    seconds = time.perf_counter() - started
    run = result["run"]
    rec = receipt(run.totals(), run.steps, seconds, title="This search")
    if not result["ok"]:
        kind = "bad" if result.get("blocked") or result.get("budget") else "info"
        return [notice(kind, result["message"]), rec], no_update

    city = result.get("city") or ""
    if not result["groups"]:
        points = known_points(city)
        center = None if points else _city_center(city)
        return [*_city_overview(city), rec], map_src(points, center=center, title=f"Teams in {city.split(',')[0]}")

    blocks: list = []
    extra_points: list[dict] = []
    highlight = []
    for group in result["groups"]:
        highlight.append(group["team"])
        shown = [s for s in group["spots"] if s["status"] != "rejected"]
        rejected = [s for s in group["spots"] if s["status"] == "rejected"]
        suggestions = mk.suggestions_for(group["team"], group["city"])
        head = [html.Div(className="row", children=[team_badge(group["team"], group.get("sport", ""), 40), html.H3(f"{group['team']} · {group['city']}")])]
        if group.get("club_name"):
            club_line = [html.Span("Official club: ", style={"color": "#c9d3e6"}), html.B(group["club_name"])]
            if group.get("club_contact_url"):
                club_line += [html.Span(" · "), html.A("club page", href=group["club_contact_url"], target="_blank")]
            head.append(html.Div(club_line, className="small"))
        head.append(html.Div(f"{len(shown)} spot(s) · updated {group.get('found_at', '')[:10]}", className="tiny", style={"color": "#c9d3e6", "marginTop": "4px"}))
        tinfo = lookup(group["team"], group.get("sport", ""))
        blocks.append(html.Div(head, className="group-head", style={"background": f"linear-gradient(135deg, {tinfo['color']} 0%, #0f2240 85%)"}))
        blocks += [spot_card(s) for s in shown]
        blocks += [_suggestion_card(s) for s in suggestions]
        if not shown and not suggestions:
            blocks.append(notice("info", f"No bar we could tie to {group['team']} fans in {group['city'].split(',')[0]} yet. {group.get('search_notes') or ''}"))
        if not group.get("wide_done") and not any(x["status"] in ("confirmed", "likely") for x in shown):
            blocks.append(html.Div(className="suggest", children=[
                html.Div(className="row", children=[
                    html.Div([html.B("Not sure about these?"), html.Div(f"Search the whole {group['city'].split(',')[0]} area, fan club directories, and every-game sports bars (about 10 s).", className="tiny muted")], style={"flex": 1}),
                    html.Button("Search wider", id={"type": "widen-go", "index": f"{group['team']}|{group['city']}|{group.get('sport', '')}"}, className="btn btn-gold btn-sm"),
                ])]))
        allgames = group.get("allgames") or []
        if allgames and not shown:
            blocks.append(html.Div(f"Best bets: verified sports bars that show every game", className="section-sub"))
            blocks += [spot_card(a) for a in allgames]
            for a in allgames:
                if a.get("lat") is not None:
                    extra_points.append({"bar_name": a["bar_name"], "address": a["address"], "lat": a["lat"], "lon": a["lon"], "bar_id": a.get("bar_id"),
                                         "teams": [{"team": group["team"], "status": "allgames", "club": "Shows every game", "sport": group.get("sport", "")}]})
        if rejected:
            blocks.append(html.Details([html.Summary(f"{len(rejected)} candidate(s) filtered out by the Verifier", className="small muted"), *[spot_card(s) for s in rejected]]))
        if group.get("search_notes") and shown:
            blocks.append(html.Div(group["search_notes"], className="tiny muted"))
        blocks.append(_suggest_form(group["team"], group["city"]))
        blocks.append(dcc.Link(f"See every team's fans in {group['city'].split(',')[0]} →", href=search_href(group["city"].split(",")[0]), className="small"))
    blocks.append(rec)
    points = known_points(city) + extra_points
    center = None if points else _city_center(city)
    return blocks, map_src(points, highlight=highlight, center=center, title=f"Teams in {city.split(',')[0]}")


def _city_center(city: str) -> dict | None:
    from tools.geocode import geocode
    g = geocode(city)
    return {"lat": g["lat"], "lon": g["lon"]} if g else None


@callback(
    Output("sug-msg", "children"),
    Input("sug-go", "n_clicks"),
    State("sug-bar", "value"), State("sug-address", "value"), State("sug-team", "value"), State("sug-city", "value"), State("sug-url", "value"),
    State("session", "data"),
    prevent_initial_call=True, running=[(Output("sug-go", "disabled"), True, False)],
)
def suggest(_n, bar, address, team, city, url, session):
    res = mk.suggest_spot(bar or "", address or "", city or "", team or "", url or "", (session or {}).get("user"), (session or {}).get("sid", "anon"))
    return notice("ok" if res["ok"] else "bad", res["message"] + (" Search again to see it on the map." if res["ok"] else ""))


@callback(
    Output("find-results", "children", allow_duplicate=True),
    Output("find-map", "src", allow_duplicate=True),
    Input("sweep-go", "n_clicks"), State("sweep-city", "data"), State("session", "data"),
    prevent_initial_call=True, running=[(Output("sweep-go", "disabled"), True, False)],
)
def run_sweep(_n, city, session):
    from agents.city_sweep import city_sweep
    from agents.llm import AgentError
    from core.budget import BudgetExceeded, Run

    run = Run(kind="city_sweep", session_id=(session or {}).get("sid", "anon"))
    t0 = time.perf_counter()
    try:
        out = city_sweep(run, city)
        msg = notice("ok", f"🎉 Added {out['teams']} teams' fan spots to the {city.split(',')[0]} map.")
    except (BudgetExceeded, AgentError) as exc:
        msg = notice("bad", str(exc))
    rec = receipt(run.totals(), run.steps, time.perf_counter() - t0, title="City Sweep run")
    points = known_points(city)
    return [msg, *_city_overview(city), rec], map_src(points, center=None if points else _city_center(city), title=f"Teams in {city.split(',')[0]}")


@callback(
    Output("find-autorun", "data", allow_duplicate=True),
    Input({"type": "widen-go", "index": ALL}, "n_clicks"),
    State("find-q", "value"), State("session", "data"),
    prevent_initial_call=True,
)
def widen(clicks, query, session):
    from core.orchestrator import widen_search

    if not ctx.triggered_id or not any(clicks or []):
        return no_update
    team, city, sport = ctx.triggered_id["index"].split("|")
    widen_search(team, city, sport or None, (session or {}).get("sid", "anon"))
    return query + " "  # re-run the (now cached) search to show the wider results
