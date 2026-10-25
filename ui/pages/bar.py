"""Bar page: profile, game-day score from reviews, reviews, and posting a review (Guard-screened)."""

from __future__ import annotations

from dash import Input, Output, State, callback, dcc, html, no_update

import time

from agents.llm import AgentError
from agents.reputation import external_links, reputation, street_view
from agents.summarizer import summarize
from core import marketplace as mk
from core.budget import BudgetExceeded, Run
from core.citymap import known_points
from ui.fun import football_spinner
from ui.components import empty_state, notice, receipt, stars
from ui.logo_map import iframe_style, map_src


def _score_block(bar_id: int, sid: str) -> html.Div:
    run = Run(kind="summary", session_id=sid)
    try:
        s = summarize(run, bar_id)
    except Exception as exc:  # noqa: BLE001
        return notice("warn", f"Game-day score unavailable right now ({type(exc).__name__}).")
    if not s:
        return html.Div("No reviews yet, so no game-day score. Be the first to review a game here.", className="muted")
    pct = (s["overall"] / 5) * 100
    cost_line = "summarized from fan reviews"
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
    here = [p for p in known_points(b["city"]) if p.get("bar_id") == bar_id or p["bar_name"].lower() == b["name"].lower()]
    if not here and b["lat"] is not None:
        here = [{"bar_name": b["name"], "address": b["address"], "lat": b["lat"], "lon": b["lon"], "bar_id": b["id"],
                 "teams": [{"team": t.strip(), "status": "partner" if b["is_demo"] else "likely", "club": ""} for t in (b["teams_hosted"] or "").split(",") if t.strip()]
                 or [{"team": b["name"], "status": "unverified", "club": ""}]}]
    links = external_links(b["name"], b["address"] or "", b["city"] or "")
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
                html.Div(className="card", children=[
                    html.Div(className="card-head", children=[html.H3("Photos & public reviews"), html.Span("from around the web", className="badge gold")]),
                    html.Div(className="ext-links", children=[
                        html.A("Open in Google Maps ↗", href=links["google"], target="_blank", className="btn btn-ghost btn-sm"),
                        html.A("Open on Yelp ↗", href=links["yelp"], target="_blank", className="btn btn-ghost btn-sm"),
                    ]),
                    dcc.Loading(html.Div(id="rep-slot", style={"marginTop": "10px"}), custom_spinner=football_spinner()),
                ]),
                html.Div(className="card", children=[_score_block(bar_id, sid)]),
            ]),
            html.Div([
                html.Div(className="card", style={"padding": 0, "overflow": "hidden", "height": "280px"},
                         children=html.Iframe(src=map_src(here, highlight=[t["team"] for p in here for t in p["teams"]], title="Teams that watch here"), style=iframe_style("280px"))) if here else None,
                html.Div(className="card", style={"padding": "0", "overflow": "hidden"}, children=[
                    html.Div(className="row", style={"padding": "10px 14px 6px"}, children=[
                        html.B("On Google Maps", className="small"), html.Div(className="spacer"),
                        html.A("Photos, menu & reviews on Google ↗", href=links["google"], target="_blank", className="btn btn-ghost btn-sm"),
                    ]),
                    html.Iframe(src=links["google_embed"], style={"width": "100%", "height": "320px", "border": "0", "display": "block"},
                                referrerPolicy="no-referrer-when-downgrade"),
                ]) if not b["is_demo"] else None,
                html.Div(className="card", style={"padding": "0", "overflow": "hidden"}, children=[
                    html.Div([html.B("Look inside & outside", className="small"),
                              html.Span(" · Google Street View: drag to look around", className="tiny muted")], style={"padding": "10px 14px 6px"}),
                    html.Iframe(src=street_view(b["lat"], b["lon"]), style={"width": "100%", "height": "300px", "border": "0", "display": "block"},
                                referrerPolicy="no-referrer-when-downgrade"),
                ]) if not b["is_demo"] and b["lat"] is not None else None,
                html.Div(className="card", children=[
                    html.H3("Review a game here"),
                    html.P("Tell other fans about the TVs, the sound, and the crowd. Reviews are checked for spam before they post.", className="small muted"),
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
    if res["ok"]:
        return notice("ok", "🎉 Posted. Thanks! The game-day score updates on the next visit."), _reviews_list(bar_id), ""
    return notice("bad", f"We couldn't post that review. {v['reason']}"), no_update, no_update


@callback(Output("claim-msg", "children"), Input("claim-btn", "n_clicks"), State("bar-id", "data"), State("session", "data"), prevent_initial_call=True)
def claim(_n, bar_id, session):
    user = mk.user((session or {}).get("user"))
    if not user or user["role"] != "bar":
        return notice("info", "Log in as a bar manager to claim a bar.")
    return notice("ok", mk.claim_bar(bar_id, user["id"])["message"])


@callback(Output("rep-slot", "children"), Input("bar-id", "data"), State("session", "data"))
def load_reputation(bar_id, session):
    b = mk.bar(bar_id)
    if not b:
        return no_update
    if b["is_demo"]:
        return html.Div("Demo profile: this venue is fictional, so it has no public reviews or photos. Real bars found by the Scout show their web reputation here.", className="small muted")
    run = Run(kind="reputation", session_id=(session or {}).get("sid", "anon"))
    t0 = time.perf_counter()
    try:
        rep = reputation(run, b)
    except (BudgetExceeded, AgentError) as exc:
        return notice("warn", f"Public reviews unavailable right now: {exc}")
    if not rep:
        return no_update
    photos = rep.get("photos") or []
    ratings = []
    if rep.get("google_rating"):
        ratings.append(html.Span([html.B(f"{rep['google_rating']:.1f}"), " ★ Google"], className="badge navy"))
    if rep.get("yelp_rating"):
        ratings.append(html.Span([html.B(f"{rep['yelp_rating']:.1f}"), " ★ Yelp"], className="badge navy"))
    icon = {"positive": "▲", "mixed": "◆", "negative": "▼"}
    color = {"positive": "#1f7a4d", "mixed": "#b7791f", "negative": "#b42d2d"}
    return html.Div([
        html.Div(className="grid-2", style={"gap": "8px", "marginBottom": "10px"},
                 children=[html.A(html.Img(src=u, className="bar-photo", style={"height": "140px"}), href=u, target="_blank") for u in photos[:4]]) if photos else
        html.Div("No photos published on the bar's website.", className="tiny muted"),
        html.Div(photos and f"Photos: the bar's own website ({(rep.get('official_site') or '').replace('https://', '').strip('/')})" or "", className="tiny muted"),
        html.Div(ratings + [html.Span(rep.get("review_volume") or "", className="tiny muted")], className="row", style={"marginTop": "10px"}),
        html.Div(className="ext-links", children=[
            html.A("🍔 Menu ↗", href=rep["menu_url"], target="_blank", className="btn btn-ghost btn-sm") if rep.get("menu_url") else None,
            html.A("🌐 Bar website ↗", href=rep["official_site"], target="_blank", className="btn btn-ghost btn-sm") if rep.get("official_site") else None,
        ]),
        html.P(rep.get("game_day_take") or "", style={"marginTop": "8px", "fontWeight": 600}),
        html.Div([html.Div([html.Span(icon[t["sentiment"]] + " ", style={"color": color[t["sentiment"]]}), html.B(t["theme"] + ": "), t["detail"]], className="rep-theme")
                  for t in rep.get("themes", [])]),
        html.Div(["Summary of public reviews from: "] +
                 [x for i, u in enumerate(rep.get("sources", [])[:4]) for x in ((" · " if i else ""), html.A(u.split("/")[2], href=u, target="_blank"))],
                 className="tiny muted", style={"marginTop": "8px"}),
        html.Div(receipt(run.totals(), run.steps, time.perf_counter() - t0, title="Reputation run"), style={"marginTop": "10px"}) if not rep.get("cached") else None,
    ])
