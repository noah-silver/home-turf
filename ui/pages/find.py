"""Find a watch spot: search box, verified results list, map, and a run receipt."""

from __future__ import annotations

import time
from urllib.parse import parse_qs

from dash import Input, Output, State, callback, dcc, html, no_update

from core import db
from core.orchestrator import find_watch_spots
from ui.components import empty_state, map_figure, notice, receipt, search_href, spot_card

CHIPS = ["USC fans in Chicago", "Chicago Bears fans in Boston", "Harvard vs Yale in Chicago", "Packers fans in Boston", "Michigan fans in Chicago"]


def layout(search: str = "") -> html.Div:
    q = parse_qs((search or "").lstrip("?")).get("q", [""])[0]
    return html.Div(
        className="page",
        children=[
            dcc.Store(id="find-autorun", data=q),
            html.Div(
                className="find-layout",
                children=[
                    html.Div([
                        html.Div("Find a watch spot", className="eyebrow"),
                        html.H2("Where do your fans watch?"),
                        html.Div(className="searchbar", children=[
                            dcc.Input(id="find-q", type="text", value=q, placeholder="Team + city, e.g. “USC fans in Chicago”", n_submit=0, maxLength=300),
                            html.Button("Search", id="find-go", className="btn btn-gold"),
                        ]),
                        html.Div([dcc.Link(c, href=search_href(c), className="chip light") for c in CHIPS], className="chips"),
                        html.Div(className="legend", style={"marginTop": "12px"}, children=[
                            html.Span([html.Span(className="dot", style={"background": "#1f7a4d"}), "Verified"]),
                            html.Span([html.Span(className="dot", style={"background": "#b7791f"}), "Likely"]),
                            html.Span([html.Span(className="dot", style={"background": "#7b8699"}), "Unverified"]),
                            html.Span([html.Span(className="dot", style={"background": "#b8902f"}), "Home Turf partner bar"]),
                        ]),
                        dcc.Loading(
                            type="dot", color="#b8902f",
                            children=html.Div(id="find-results", className="results", children=empty_state(
                                "🏟️", "Search any team and city", "Results are checked against their sources before they show up here. A new search takes about 10–20 seconds; searches we have seen before load instantly from cache.")),
                        ),
                    ]),
                    html.Div(className="card map-card", children=dcc.Graph(id="find-map", figure=map_figure([]), config={"displayModeBar": False, "scrollZoom": True, "responsive": True}, style={"height": "100%", "width": "100%"})),
                ],
            ),
        ],
    )


def _partner_points(city: str) -> list[dict]:
    key = city.split(",")[0].lower()
    rows = db.query("SELECT id, name, lat, lon, city, capacity, tvs FROM bars WHERE is_demo = 1 AND claimed = 1")
    return [
        {"lat": r["lat"], "lon": r["lon"], "status": "demo", "bar_id": r["id"],
         "label": f"<b>{r['name']}</b><br>Home Turf partner (demo) · holds {r['capacity']} · {r['tvs']} TVs"}
        for r in rows if (r["city"] or "").split(",")[0].lower() == key
    ]


@callback(
    Output("find-results", "children"),
    Output("find-map", "figure"),
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
    totals = run.totals()
    rec = receipt(totals, run.steps, seconds, title="This search")
    if not result["ok"]:
        kind = "bad" if result.get("blocked") or result.get("budget") else "info"
        return [notice(kind, result["message"]), rec], no_update

    blocks: list = []
    points: list[dict] = []
    cities = set()
    for group in result["groups"]:
        cities.add(group["city"])
        shown = [s for s in group["spots"] if s["status"] != "rejected"]
        rejected = [s for s in group["spots"] if s["status"] == "rejected"]
        head = [html.H3(f"{group['team']} · {group['city']}")]
        if group.get("club_name"):
            club_line = [html.Span("Official club: ", style={"color": "#c9d3e6"}), html.B(group["club_name"])]
            if group.get("club_contact_url"):
                club_line += [html.Span(" · "), html.A("club page", href=group["club_contact_url"], target="_blank")]
            head.append(html.Div(club_line, className="small"))
        src = "from cache · no tokens" if group.get("from_cache") else "live search"
        head.append(html.Div(f"{len(shown)} spot(s) · {src} · found {group.get('found_at', '')[:10]}", className="tiny", style={"color": "#9fb0cc", "marginTop": "4px"}))
        blocks.append(html.Div(head, className="group-head"))
        if not shown:
            blocks.append(notice("info", group.get("search_notes") or "No reliable watch spot found for this team and city."))
        blocks += [spot_card(s) for s in shown]
        if rejected:
            blocks.append(html.Details([html.Summary(f"{len(rejected)} candidate(s) filtered out by the Verifier", className="small muted"), *[spot_card(s) for s in rejected]]))
        if group.get("search_notes") and shown:
            blocks.append(html.Div(group["search_notes"], className="tiny muted"))
        for s in shown:
            if s.get("lat") is not None:
                points.append({"lat": s["lat"], "lon": s["lon"], "status": s["status"], "bar_id": s.get("bar_id"),
                               "label": f"<b>{s['bar_name']}</b><br>{group['team']} · {s['status']}<br>{s['address']}"})
    for city in cities:
        points += _partner_points(city)
    blocks.append(rec)
    return blocks, map_figure(points, zoom=11.2)


@callback(Output("url", "href", allow_duplicate=True), Input("find-map", "clickData"), prevent_initial_call=True)
def open_bar(click):
    try:
        bar_id = click["points"][0]["customdata"]
    except (TypeError, KeyError, IndexError):
        return no_update
    return f"/bar/{bar_id}" if bar_id else no_update
