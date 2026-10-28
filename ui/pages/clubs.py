"""Fan-club president dashboard: Season Matchmaker, bar pitches inbox, rivalry planner, approvals."""

from __future__ import annotations

import time

from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from agents.llm import AgentError
from agents.matchmaker import rivalry_plan, season_plan
from core import marketplace as mk
from core.budget import BudgetExceeded, Run
from ui.fun import football_spinner
from ui.components import empty_state, notice, receipt


def _login_needed(role_word: str) -> html.Div:
    return html.Div(className="page", children=html.Div(className="card", children=empty_state(
        "🔑", f"Log in as a {role_word}", "Use the Demo login menu at the top right. Each demo account is a fictional person running a labeled demo club or bar.")))


RIVAL_PAIRS = [("Yale", "Princeton"), ("USC", "UCLA"), ("Michigan", "Ohio State"), ("Yale", "Harvard"), ("Bears", "Packers"), ("Patriots", "Bills"),
               ("Liverpool", "Manchester United"), ("Yankees", "Red Sox"), ("Bruins", "Rangers"), ("Knicks", "Celtics"), ("Notre Dame", "USC")]


def _default_rival(club: dict, rivals: list[dict]) -> int | None:
    for a, b in RIVAL_PAIRS:
        for mine, theirs in ((a, b), (b, a)):
            if mine in club["team"]:
                for r in rivals:
                    if theirs in r["team"]:
                        return r["id"]
    return None


def _team_avatar(team: str, sport: str) -> html.Div:
    from ui.team_logos import lookup

    t = lookup(team, sport)
    if t["logo"]:
        return html.Div(html.Img(src=t["logo"], style={"width": "46px", "height": "46px", "objectFit": "contain"}), className="avatar",
                        style={"background": "#fff", "border": f"3px solid {t['color']}"})
    return html.Div(t["abbr"], className="avatar")


def layout(session: dict | None) -> html.Div:
    user = mk.user((session or {}).get("user"))
    if not user or user["role"] != "president":
        return _login_needed("fan-club president")
    c = mk.club(user["club_id"])
    home = mk.bar(c["home_bar_id"]) if c["home_bar_id"] else None
    rivals = [r for r in mk.clubs_in_city(c["city"]) if r["id"] != c["id"]]
    import config

    sample = [html.Div("Sample marketplace: these clubs, bars, and people are fictional, to show how clubs and bars would use Home Turf. Fan searches and maps use real data.",
                       className="notice info", style={"marginBottom": "14px"})] if config.REAL_ONLY else []
    return html.Div(className="page", children=[*sample,
        dcc.Store(id="club-id", data=c["id"]),
        dcc.Store(id="club-refresh", data=0),
        dcc.Store(id="rivalry-result"),
        html.Div(className="dash-head", children=[
            _team_avatar(c["team"], c["sport"]),
            html.Div([
                html.Div("Club president dashboard", className="eyebrow"),
                html.H1(c["name"], style={"fontSize": "1.9rem", "margin": 0}),
                html.Div(f"{c['team']} · {c['sport']} · {c['city']} · usually {c['typical_turnout']} fans · prefers {c['preferred_area']}", className="muted"),
            ], style={"flex": 1}),
            html.Div([html.Div("Season home bar", className="tiny muted"), html.B(home["name"] if home else "Not chosen yet")], className="card", style={"padding": "12px 16px"}),
        ]),
        html.Div(className="grid-2", children=[
            html.Div([
                html.Div(className="card", children=[
                    html.Div(className="card-head", children=[html.H3("Find our season home bar"), html.Span("🏠", className="badge gold")]),
                    html.P("We rank every bar in your city for your club: room for your crowd, TVs, game sound, location, and clashes with other clubs' games at the same bar.", className="small muted"),
                    html.Div(f"What you need: {c['needs']}", className="quote"),
                    html.Button("Rank bars for our season", id="season-go", className="btn btn-gold"),
                    dcc.Loading(html.Div(id="season-out"), custom_spinner=football_spinner()),
                ]),
                html.Div(className="card", children=[
                    html.Div(className="card-head", children=[html.H3("Pitches from bars"), html.Span("inbox", className="badge navy")]),
                    html.Div(id="club-inbox"),
                ]),
            ]),
            html.Div([
                html.Div(className="card", children=[
                    html.Div(className="card-head", children=[html.H3("Rivalry watch party"), html.Span("⚔️", className="badge gold")]),
                    html.P("Pick a rival club in your city. We find your game, shortlist neutral bars that can hold both crowds, and draft invitations for both presidents and the bar. Nothing is sent or booked until all three say yes.", className="small muted"),
                    dcc.Dropdown(id="rival-dd", options=[{"label": f"{r['name']} ({r['team']})", "value": r["id"]} for r in rivals],
                                 value=_default_rival(c, rivals),
                                 placeholder="Choose a rival club", clearable=False),
                    html.Button("Plan rivalry watch party", id="rivalry-go", className="btn btn-gold", style={"marginTop": "10px"}),
                    dcc.Loading(html.Div(id="rivalry-out"), custom_spinner=football_spinner()),
                ]),
                html.Div(className="card", children=[
                    html.Div(className="card-head", children=[html.H3("Watch parties and approvals"), html.Span("everyone signs off", className="badge navy")]),
                    html.Div(id="club-events"),
                ]),
            ]),
        ]),
    ])


def _rank_cards(ranked: list[dict], facts: dict, recommended: int, choose_type: str | None) -> list:
    cards = []
    for i, r in enumerate(ranked):
        f = facts.get(r["bar_id"]) or facts.get(str(r["bar_id"])) or {}
        conflicts = f.get("conflicts", [])
        top = r["bar_id"] == recommended
        cards.append(html.Div(className=f"rank-card{' top' if top else ''}", style={"marginTop": "10px"}, children=[
            html.Div(className="row", children=[
                html.Button(f"{i + 1}. {f.get('name', r['bar_id'])}", id={"type": "view-bar", "index": r["bar_id"]}, className="bar-link h4", title="View bar profile"),
                html.Span("recommended", className="badge gold") if top else None,
                html.Span(f.get("neighborhood") or "", className="small muted"),
            ]),
            html.Div(className="fit", children=[html.Div(className="fit-bar", children=html.Div(style={"width": f"{r['fit_score']}%"})), html.Div(f"{r['fit_score']}", className="fit-num")]),
            html.Div(f"Holds {f.get('capacity') or '?'} · {f.get('tvs') or '?'} TVs", className="tiny muted"),
            html.P(r["why"], className="small", style={"margin": "6px 0"}),
            *[html.Div("⚠ " + x, className="concern") for x in r["concerns"][:3]],
            *[html.Div(f"Schedule clash ({cf['kind']}): {cf['date']} · your game {cf['our_game']} vs. {cf['their_club']}: {cf['their_game']}", className="conflict") for cf in conflicts[:3]],
            html.Div(className="row", style={"marginTop": "8px"}, children=[
                html.Button("👀 View bar: photos, reviews, menu", id={"type": "view-bar", "index": r["bar_id"]}, className="btn btn-ghost btn-sm"),
                html.Button("Make this our season home bar", id={"type": choose_type, "index": r["bar_id"]}, className="btn btn-navy btn-sm") if choose_type else None,
            ]),
        ]))
    return cards


@callback(
    Output("season-out", "children"),
    Input("season-go", "n_clicks"), State("club-id", "data"), State("session", "data"),
    prevent_initial_call=True, running=[(Output("season-go", "disabled"), True, False)],
)
def run_season(_n, club_id, session):
    run = Run(kind="season_match", session_id=(session or {}).get("sid", "anon"))
    t0 = time.perf_counter()
    try:
        out = season_plan(run, club_id)
    except (BudgetExceeded, AgentError) as exc:
        return [notice("bad", str(exc)), receipt(run.totals(), run.steps)]
    if "error" in out:
        return notice("info", out["error"])
    p = out["plan"]
    return [
        html.P(p["summary"], style={"marginTop": "12px"}),
        *_rank_cards(p["ranked"], out["facts"], p["recommended_bar_id"], "choose-home"),
        html.Div([html.H4("Schedule clashes, explained", style={"marginTop": "14px"}), html.Ul([html.Li(x, className="small") for x in p["conflicts_explained"]])]) if p["conflicts_explained"] else None,
        html.Div(id="choose-msg"),
        html.Div(receipt(run.totals(), run.steps, time.perf_counter() - t0, title="Matchmaker run"), style={"marginTop": "12px"}),
    ]


@callback(
    Output("choose-msg", "children"), Output("club-refresh", "data", allow_duplicate=True),
    Input({"type": "choose-home", "index": ALL}, "n_clicks"), State("club-id", "data"), State("session", "data"), State("club-refresh", "data"),
    prevent_initial_call=True,
)
def choose_home(clicks, club_id, session, refresh):
    if not ctx.triggered_id or not any(clicks):
        return no_update, no_update
    bar_id = ctx.triggered_id["index"]
    mk.set_home_bar(club_id, bar_id, (session or {}).get("user"))
    return notice("ok", f"🎉 Confirmed by you: {mk.bar(bar_id)['name']} is your {mk.config.CURRENT_SEASON} season home bar."), (refresh or 0) + 1


@callback(Output("club-inbox", "children"), Input("club-refresh", "data"), State("club-id", "data"))
def render_inbox(_r, club_id):
    rows = mk.pitches_for_club(club_id)
    if not rows:
        return html.Div("No pitches yet. Bars on Home Turf can invite your club; they will show up here.", className="muted small")
    out = []
    for p in rows:
        pending = p["status"] == "in_club_inbox"
        out.append(html.Div(className="rank-card", style={"marginTop": "10px"}, children=[
            html.Div(className="row", children=[html.Button(p["bar_name"], id={"type": "view-bar", "index": p["bar_id"]}, className="bar-link", title="View bar profile"),
                                                html.Span(p["status"].replace("_", " "), className="badge navy"), html.Span(p["created_at"][:10], className="tiny muted")]),
            html.Div(p["subject"], style={"fontWeight": 600, "marginTop": "6px"}),
            html.Div(p["body"], className="draft", style={"marginTop": "6px"}),
            html.Div(className="row", style={"marginTop": "8px"}, children=[
                html.Button("Accept as home bar", id={"type": "pitch-accept", "index": p["id"]}, className="btn btn-green btn-sm"),
                html.Button("Decline", id={"type": "pitch-decline", "index": p["id"]}, className="btn btn-red btn-sm"),
            ]) if pending else None,
        ]))
    return out


@callback(
    Output("club-refresh", "data", allow_duplicate=True),
    Input({"type": "pitch-accept", "index": ALL}, "n_clicks"), Input({"type": "pitch-decline", "index": ALL}, "n_clicks"),
    State("session", "data"), State("club-refresh", "data"), prevent_initial_call=True,
)
def answer_pitch(acc, dec, session, refresh):
    if not ctx.triggered_id or not any((acc or []) + (dec or [])):
        return no_update
    mk.respond_to_pitch(ctx.triggered_id["index"], ctx.triggered_id["type"] == "pitch-accept", (session or {}).get("user"))
    return (refresh or 0) + 1


@callback(
    Output("rivalry-out", "children"), Output("rivalry-result", "data"),
    Input("rivalry-go", "n_clicks"), State("club-id", "data"), State("rival-dd", "value"), State("session", "data"),
    prevent_initial_call=True, running=[(Output("rivalry-go", "disabled"), True, False)],
)
def run_rivalry(_n, club_id, rival_id, session):
    if not rival_id:
        return notice("info", "Choose a rival club first."), no_update
    run = Run(kind="rivalry_match", session_id=(session or {}).get("sid", "anon"))
    t0 = time.perf_counter()
    try:
        out = rivalry_plan(run, club_id, rival_id)
    except (BudgetExceeded, AgentError) as exc:
        return [notice("bad", str(exc)), receipt(run.totals(), run.steps)], no_update
    if "error" in out:
        return [notice("info", out["error"]), receipt(run.totals(), run.steps)], no_update
    p, g = out["plan"], out["game"]
    rec_bar = mk.bar(p["recommended_bar_id"])
    to_label = {"club_a": out["club_a"]["name"], "club_b": out["club_b"]["name"], "bar": rec_bar["name"] if rec_bar else "the bar"}
    view = [
        html.Div(className="rank-card top", style={"marginTop": "12px"}, children=[
            html.Div(f"{g['date']} · {g['kickoff_et']} · {g['tv']}", className="eyebrow"),
            html.H3(p["title"]),
            html.P(p["summary"], className="small"),
            html.Div(f"Combined turnout: {out['combined']} fans · Recommended: {rec_bar['name'] if rec_bar else '?'}", className="small", style={"fontWeight": 600}),
            html.Ul([html.Li(x, className="small") for x in p["logistics"]]),
            *[html.Div("Code check: " + n, className="notice warn") for n in p["safety_notes"] if n.startswith("Recommendation changed")],
        ]),
        *_rank_cards(p["ranked"][:3], out["facts"], p["recommended_bar_id"], None),
        html.H4("Drafted invitations (not sent)", style={"marginTop": "16px"}),
        *[html.Div([html.Div(f"To: {to_label.get(d['to'], d['to'])} · {d['subject']}", className="small", style={"fontWeight": 600, "marginTop": "8px"}),
                    html.Div(d["body"], className="draft")]) for d in p["drafts"]],
        html.Button("Propose to the other club and the bar", id="rivalry-propose", className="btn btn-navy", style={"marginTop": "12px"}),
        html.Div(id="propose-msg"),
        html.Div(receipt(run.totals(), run.steps, time.perf_counter() - t0, title="Rivalry planner run"), style={"marginTop": "12px"}),
    ]
    store = {"plan": p, "game": g, "club_a": {"id": out["club_a"]["id"]}, "club_b": {"id": out["club_b"]["id"]}}
    return view, store


@callback(
    Output("propose-msg", "children"), Output("club-refresh", "data", allow_duplicate=True),
    Input("rivalry-propose", "n_clicks"), State("rivalry-result", "data"), State("session", "data"), State("club-refresh", "data"),
    prevent_initial_call=True,
)
def propose(_n, result, session, refresh):
    if not result:
        return no_update, no_update
    eid = mk.propose_event(result, result["plan"]["recommended_bar_id"], (session or {}).get("user"))
    return notice("ok", f"Proposed (event #{eid}). Your approval is recorded; the other president and the bar each approve from their dashboards."), (refresh or 0) + 1


def approvals_view(events: list[dict], my_party_of, button_type: str) -> list:
    if not events:
        return [html.Div("No watch parties yet.", className="muted small")]
    out = []
    for e in events:
        bar = mk.bar(e["bar_id"])
        party = my_party_of(e)
        mine = e["approvals"].get(party, "")
        out.append(html.Div(className="rank-card", style={"marginTop": "10px"}, children=[
            html.Div(className="row", children=[html.B(e["title"]), html.Span(e["status"], className="badge confirmed" if e["status"] == "confirmed" else "badge likely")]),
            html.Div(f"{e['game']} · at {bar['name'] if bar else '?'}", className="small muted"),
            *[html.Div(className="approval", children=[html.Span("✓" if v.startswith("approved") else ("✕" if v.startswith("declined") else "…")),
                                                        html.B({"club_a": "Proposing club", "club_b": "Rival club", "bar": "Bar"}[k]), html.Span(v, className="small muted")])
              for k, v in e["approvals"].items()],
            html.Div(className="row", style={"marginTop": "8px"}, children=[
                html.Button("Approve", id={"type": f"{button_type}-yes", "index": e["id"]}, className="btn btn-green btn-sm"),
                html.Button("Decline", id={"type": f"{button_type}-no", "index": e["id"]}, className="btn btn-red btn-sm"),
            ]) if party and mine == "pending" and e["status"] == "awaiting approvals" else None,
        ]))
    return out


@callback(Output("club-events", "children"), Input("club-refresh", "data"), State("club-id", "data"))
def render_events(_r, club_id):
    events = mk.events_for(club_id=club_id)
    return approvals_view(events, lambda e: "club_a" if e["club_a"] == club_id else "club_b", "club-ev")


@callback(
    Output("club-refresh", "data", allow_duplicate=True),
    Input({"type": "club-ev-yes", "index": ALL}, "n_clicks"), Input({"type": "club-ev-no", "index": ALL}, "n_clicks"),
    State("club-id", "data"), State("session", "data"), State("club-refresh", "data"), prevent_initial_call=True,
)
def club_approve(yes, no, club_id, session, refresh):
    if not ctx.triggered_id or not any((yes or []) + (no or [])):
        return no_update
    eid = ctx.triggered_id["index"]
    e = mk.db.one("SELECT club_a FROM events WHERE id = ?", (eid,))
    party = "club_a" if e["club_a"] == club_id else "club_b"
    mk.approve_event(eid, party, (session or {}).get("user"), ctx.triggered_id["type"].endswith("yes"))
    return (refresh or 0) + 1
