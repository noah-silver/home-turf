"""Bar page: profile, game-day score from reviews, reviews, and posting a review (Guard-screened)."""

from __future__ import annotations

from dash import Input, Output, State, callback, dcc, html, no_update

from agents.summarizer import summarize
from core import marketplace as mk
from core.budget import Run
from ui.components import empty_state, map_figure, notice, stars


def _score_block(bar_id: int, sid: str) -> html.Div:
    run = Run(kind="summary", session_id=sid)
    try:
        s = summarize(run, bar_id)
    except Exception as exc:  # noqa: BLE001
        return notice("warn", f"Game-day score unavailable right now ({type(exc).__name__}).")
    if not s:
        return html.Div("No reviews yet, so no game-day score. Be the first to review a game here.", className="muted")
    pct = (s["overall"] / 5) * 100
    t = run.totals()["total"]
    cost_line = "score from cache (no tokens)" if s.get("cached") else f"scored by the Summarizer agent: {t['input'] + t['output']:,} tokens, ${t['cost']:.5f}"
    return html.Div([
        html.Div(className="row", children=[
            html.Div(className="score-ring", style={"--pct": f"{pct:.0f}"}, children=html.Div(f"{s['overall']:.1f}")),
            html.Div([html.H3("Game-day score"), html.P(s["one_liner"], style={"maxWidth": "520px"}),
                      html.Div([html.Span(t, className="badge gold", style={"marginRight": "6px"}) for t in s["best_for"]])], style={"flex": 1}),
        ]),
        html.Div(className="subscores", style={"marginTop": "14px"}, children=[
            html.Div([html.Div(s[k], className="n"), html.Div(label, className="l")], className="subscore")
            for k, label in (("tvs", "TVs"), ("sound", "Game sound"), ("crowd", "Crowd"), ("service", "Service"))
        ]),
        html.Div([html.Div("Watch-outs: " + "; ".join(s["watch_outs"]), className="concern")] if s["watch_outs"] else [], style={"marginTop": "8px"}),
        html.Div(f"Based on {s['based_on']} posted reviews · {cost_line}", className="tiny muted", style={"marginTop": "8px"}),
    ])


def _reviews_list(bar_id: int) -> html.Div:
    rows = mk.reviews_for(bar_id)
    if not rows:
        return html.Div("No reviews yet.", className="muted")
    return html.Div([
        html.Div(className="review", children=[
            html.Div(className="row", children=[html.Span(stars(r["rating"]), className="stars"), html.B(r["team"] or "Fan"),
                                                html.Span("seed review" if r["is_seed"] else r["author"], className="badge demo" if r["is_seed"] else "badge navy")]),
            html.Div(r["text"], style={"marginTop": "4px"}),
        ]) for r in rows
    ])


def layout(bar_id: int, session: dict | None) -> html.Div:
    b = mk.bar(bar_id)
    if not b:
        return html.Div(className="page", children=empty_state("🤷", "Bar not found", "It may have been removed."))
    sid = (session or {}).get("sid", "anon")
    user = mk.user((session or {}).get("user"))
    facts = [("Neighborhood", b["neighborhood"] or "—"), ("Address", b["address"] or "—"), ("Capacity", b["capacity"] or "not listed"),
             ("TVs", b["tvs"] or "not listed"), ("Game sound", b["sound_policy"] or "not listed"), ("Specials", b["specials"] or "not listed"),
             ("Teams hosted", b["teams_hosted"] or "—")]
    clubs_here = [c["name"] for c in mk.db.query("SELECT name FROM clubs WHERE home_bar_id = ?", (bar_id,))]
    tags = []
    if b["is_demo"]:
        tags.append(html.Span("demo profile", className="badge demo"))
    tags.append(html.Span("claimed by the bar" if b["claimed"] else "unclaimed · found by the Scout", className="badge gold" if b["claimed"] else "badge unverified"))
    claim = None
    if not b["claimed"] and user and user["role"] == "bar":
        claim = html.Div([html.Button("Claim this bar", id="claim-btn", className="btn btn-gold btn-sm"), html.Div(id="claim-msg")], style={"marginTop": "12px"})
    point = [{"lat": b["lat"], "lon": b["lon"], "status": "confirmed" if not b["is_demo"] else "demo", "label": b["name"], "bar_id": b["id"]}] if b["lat"] else []
    return html.Div(className="page", children=[
        dcc.Store(id="bar-id", data=bar_id),
        html.Div(className="dash-head", children=[
            html.Div(b["name"][:2].upper(), className="avatar"),
            html.Div([html.H1(b["name"], style={"fontSize": "2rem", "margin": 0}), html.Div(tags, className="row", style={"marginTop": "6px"})]),
        ]),
        html.Div(className="grid-2", children=[
            html.Div([
                html.Div(className="card", children=[html.H3("Profile"), html.Div([x for k, v in facts for x in (html.Div(k, className="k"), html.Div(str(v)))], className="kv"),
                    html.Div(f"Season home bar for: {', '.join(clubs_here)}", className="small", style={"marginTop": "10px"}) if clubs_here else None,
                    html.Div(f"“{b['pitch_line']}”", className="quote") if b["pitch_line"] else None, claim]),
                html.Div(className="card", children=[_score_block(bar_id, sid)]),
            ]),
            html.Div([
                html.Div(className="card", style={"padding": 0, "overflow": "hidden", "height": "260px"},
                         children=dcc.Graph(figure=map_figure(point, zoom=14), config={"displayModeBar": False, "responsive": True}, style={"height": "260px", "width": "100%"})) if point else None,
                html.Div(className="card", children=[
                    html.H3("Review a game here"),
                    html.P("Every review is screened by the Guard before it posts (spam, abuse, personal info, and AI-manipulation attempts are blocked).", className="small muted"),
                    html.Div(className="row", children=[
                        dcc.Input(id="rev-team", type="text", placeholder="Your team (e.g. USC Trojans)", style={"flex": 2}),
                        dcc.Dropdown(id="rev-rating", options=[{"label": stars(i), "value": i} for i in range(5, 0, -1)], value=5, clearable=False, style={"flex": 1, "minWidth": "150px"}),
                    ]),
                    dcc.Textarea(id="rev-text", placeholder="How was it on game day? TVs, sound, crowd, service…", maxLength=1500, style={"marginTop": "10px"}),
                    html.Div(className="row", style={"marginTop": "10px"}, children=[html.Button("Post review", id="rev-post", className="btn btn-navy"),
                        html.Span("Log in (top right) to post." if not user else f"Posting as {user['display_name']}", className="small muted")]),
                    dcc.Loading(html.Div(id="rev-msg"), type="dot", color="#b8902f"),
                ]),
                html.Div(className="card", children=[html.H3("Fan reviews"), html.Div(id="rev-list", children=_reviews_list(bar_id))]),
            ]),
        ]),
    ])


@callback(
    Output("rev-msg", "children"), Output("rev-list", "children"), Output("rev-text", "value"),
    Input("rev-post", "n_clicks"),
    State("bar-id", "data"), State("rev-team", "value"), State("rev-rating", "value"), State("rev-text", "value"), State("session", "data"),
    prevent_initial_call=True,
    running=[(Output("rev-post", "disabled"), True, False)],
)
def post_review(_n, bar_id, team, rating, text, session):
    user = mk.user((session or {}).get("user"))
    if not user:
        return notice("info", "Pick a demo login at the top right to post a review."), no_update, no_update
    if not text or not text.strip():
        return notice("info", "Write a few words about your game day first."), no_update, no_update
    res = mk.post_review(bar_id, user["id"], user["display_name"], (team or "").strip()[:60], int(rating or 5), text.strip(), (session or {}).get("sid", "anon"))
    v = res["verdict"]
    layer = "free code filter" if v["layer"] == "code" else "Guard agent"
    if res["ok"]:
        return notice("ok", "Posted. Thanks! The game-day score will update on next load."), _reviews_list(bar_id), ""
    return notice("bad", f"Blocked by the {layer} ({v['category']}): {v['reason']}"), no_update, no_update


@callback(Output("claim-msg", "children"), Input("claim-btn", "n_clicks"), State("bar-id", "data"), State("session", "data"), prevent_initial_call=True)
def claim(_n, bar_id, session):
    user = mk.user((session or {}).get("user"))
    if not user or user["role"] != "bar":
        return notice("info", "Log in as a bar manager to claim a bar.")
    return notice("ok", mk.claim_bar(bar_id, user["id"])["message"])
