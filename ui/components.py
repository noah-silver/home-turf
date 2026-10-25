"""Reusable UI pieces: top bar, badges, spot cards, run receipts, map figure."""

from __future__ import annotations

from urllib.parse import quote

import plotly.graph_objects as go
from dash import dcc, html

from core import db

QUOTE_CHARS = ' "“”\''
STATUS_LABEL = {"confirmed": "Verified", "likely": "Likely", "unverified": "Unverified", "rejected": "Rejected"}
STATUS_COLOR = {"confirmed": "#1f7a4d", "likely": "#b7791f", "unverified": "#7b8699", "rejected": "#b42d2d"}
NAV = [("/", "Home"), ("/find", "Find a watch spot"), ("/clubs", "For fan clubs"), ("/bars", "For bars"), ("/console", "Cost & safety")]


def login_options() -> list[dict]:
    users = db.query("SELECT id, role, display_name FROM users ORDER BY CASE role WHEN 'fan' THEN 0 WHEN 'president' THEN 1 ELSE 2 END, display_name")
    icon = {"fan": "Fan", "president": "Club president", "bar": "Bar manager"}
    opts = [{"label": "Browsing as guest", "value": "guest"}]
    opts += [{"label": f"{icon[u['role']]}: {u['display_name']}", "value": u["id"]} for u in users]
    return opts


def topbar(pathname: str) -> html.Div:
    links = []
    for href, label in NAV:
        active = pathname == href or (href != "/" and (pathname or "").startswith(href))
        links.append(dcc.Link(label, href=href, className="active" if active else ""))
    return html.Div(
        className="topbar",
        children=html.Div(
            className="topbar-inner",
            children=[
                dcc.Link(className="brand", href="/", children=[html.Div("HT", className="brand-mark"), html.Div(["Home ", html.Span("Turf")], className="brand-name")]),
                html.Div(links, className="nav"),
                html.Div(
                    className="login-box",
                    children=[
                        html.Span("Demo login", className="label"),
                        dcc.Dropdown(id="login-dd", options=login_options(), value="guest", clearable=False, searchable=False),
                    ],
                ),
            ],
        ),
    )


def badge(status: str) -> html.Span:
    return html.Span(STATUS_LABEL.get(status, status), className=f"badge {status}")


def check(ok: bool, text: str) -> html.Span:
    return html.Span(text, className=f"check {'ok' if ok else 'no'}")


def spot_card(spot: dict) -> html.Div:
    sources = spot.get("sources") or [{"url": spot["source_url"], "quote": spot["evidence_quote"], "official": spot.get("official_source")}]
    src_links = []
    for i, s in enumerate(sources[:3]):
        host = s["url"].split("/")[2] if "//" in s["url"] else s["url"]
        src_links.append(html.A(f"{host}{' (official)' if s.get('official') else ''}", href=s["url"], target="_blank", className="small"))
        if i < min(len(sources), 3) - 1:
            src_links.append(html.Span(" · ", className="muted"))
    from agents.reputation import external_links  # local import keeps ui light

    actions = []
    if spot.get("bar_id"):
        actions.append(dcc.Link("Bar page, photos & reviews →", href=f"/bar/{spot['bar_id']}", className="btn btn-ghost btn-sm"))
    gm = external_links(spot["bar_name"], spot.get("address", ""), spot.get("city", "") or "")["google"]
    actions.append(html.A("Google Maps ↗", href=gm, target="_blank", className="btn btn-ghost btn-sm"))
    every_game = spot.get("kind") == "allgames"
    return html.Div(
        className=f"spot {'allgames' if every_game else spot['status']}",
        children=[
            html.Div(className="row", children=[html.H4(spot["bar_name"]), html.Div(className="spacer"),
                                                html.Span("Shows every game", className="badge allgames") if every_game else badge(spot["status"])]),
            html.Div(spot["address"] if spot["address"] != "unknown" else "Address not listed by the source", className="small muted"),
            html.Div(f"Club: {spot['club_name']}" if spot.get("club_name") and spot["club_name"] != "unknown" and not every_game else "", className="small"),
            html.Div("“" + spot["evidence_quote"].strip(QUOTE_CHARS) + "”", className="quote"),
            html.Div(className="small", children=[html.Span("Sources: ", className="muted"), *src_links]),
            html.Div(
                className="checks",
                children=[
                    check(spot.get("page_loaded", False), "source re-checked"),
                    check(spot.get("name_on_page", False), "bar named on page"),
                    check(spot.get("season_on_page", False), "current season"),
                    check(spot.get("geocoded", False), "address on map"),
                ],
            ),
            html.Div(f"Why: {spot['status_reason']}  ({'code check' if spot.get('decided_by') == 'code' else 'Verifier agent'})", className="tiny muted", style={"marginTop": "6px"}),
            html.Div(actions, className="row", style={"marginTop": "8px"}) if actions else None,
        ],
    )


def receipt(totals: dict | None, steps: list[dict] | None, seconds: float | None = None, title: str = "Run receipt") -> html.Div:
    if not totals:
        return html.Div()
    t = totals["total"]
    lines = [
        html.Div([html.Span("AI calls"), html.Span(f"{t['calls']}")], className="line"),
        html.Div([html.Span("Input tokens (cached)"), html.Span(f"{t['input']:,} ({t['cached']:,})")], className="line"),
        html.Div([html.Span("Output tokens (reasoning)"), html.Span(f"{t['output']:,} ({t['reasoning']:,})")], className="line"),
        html.Div([html.Span("Web searches"), html.Span(f"{t['web_searches']}")], className="line"),
    ]
    if seconds is not None:
        lines.append(html.Div([html.Span("Time"), html.Span(f"{seconds:.1f} s")], className="line"))
    lines.append(html.Div([html.Span("Cost"), html.Span(f"${t['cost']:.4f}")], className="line total"))
    trace = [html.Li([html.B(s["agent"] + ": "), s["summary"]]) for s in (steps or [])]
    return html.Div(
        className="receipt",
        children=[
            html.H4(title),
            html.Div(lines),
            html.Hr(style={"borderColor": "rgba(255,255,255,.15)"}),
            html.H4("What each agent did"),
            html.Ul(trace, className="trace"),
        ],
    )


def search_href(q: str) -> str:
    return f"/find?q={quote(q)}"


def map_figure(points: list[dict], center: dict | None = None, zoom: float = 11) -> go.Figure:
    fig = go.Figure()
    by_status: dict[str, list[dict]] = {}
    for p in points:
        if p.get("lat") is None:
            continue
        by_status.setdefault(p["status"], []).append(p)
    for status in ("confirmed", "likely", "unverified", "rejected", "demo"):
        pts = by_status.get(status)
        if not pts:
            continue
        color = STATUS_COLOR.get(status, "#b8902f")
        fig.add_trace(
            go.Scattermap(
                lat=[p["lat"] for p in pts],
                lon=[p["lon"] for p in pts],
                mode="markers",
                marker={"size": 17 if status != "demo" else 13, "color": color, "opacity": 0.95},
                text=[p["label"] for p in pts],
                customdata=[p.get("bar_id") for p in pts],
                hovertemplate="%{text}<extra></extra>",
                name=STATUS_LABEL.get(status, "Home Turf partner bar"),
            )
        )
    if center is None:
        lats = [p["lat"] for p in points if p.get("lat") is not None]
        lons = [p["lon"] for p in points if p.get("lon") is not None]
        center = {"lat": sum(lats) / len(lats), "lon": sum(lons) / len(lons)} if lats else {"lat": 41.8781, "lon": -87.6298}
    fig.update_layout(
        map={"style": "carto-positron", "center": center, "zoom": zoom},
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        legend={"orientation": "h", "x": 0.01, "y": 0.99, "bgcolor": "rgba(255,255,255,.92)", "bordercolor": "#e3e7ee", "borderwidth": 1, "font": {"size": 12}},
        uirevision="keep",
        paper_bgcolor="#ffffff",
    )
    return fig


def empty_state(icon: str, title: str, text: str) -> html.Div:
    return html.Div(className="empty", children=[html.Div(icon, className="big"), html.H3(title), html.P(text)])


def stars(n: int) -> str:
    n = max(0, min(5, int(n or 0)))
    return "★" * n + "☆" * (5 - n)


def notice(kind: str, text) -> html.Div:
    return html.Div(text, className=f"notice {kind}")
