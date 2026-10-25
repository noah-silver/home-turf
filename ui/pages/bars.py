"""Bar manager dashboard: profile (Guard-screened), clubs in town, Pitch Writer, events to approve."""

from __future__ import annotations

import time

from dash import ALL, Input, Output, State, callback, ctx, dcc, html, no_update

from agents.llm import AgentError
from agents.pitch_writer import write_pitch
from core import marketplace as mk
from core.budget import BudgetExceeded, Run
from ui.fun import football_spinner
from ui.components import notice, receipt
from ui.pages.clubs import _login_needed, approvals_view


def layout(session: dict | None) -> html.Div:
    user = mk.user((session or {}).get("user"))
    if not user or user["role"] != "bar":
        return _login_needed("bar manager")
    b = mk.bar(user["bar_id"])
    clubs = mk.clubs_in_city(b["city"])
    fields = [("capacity", "Capacity (people)", "number"), ("tvs", "Number of TVs", "number"), ("neighborhood", "Neighborhood", "text"),
              ("sound_policy", "Game sound policy", "area"), ("specials", "Game-day specials", "area"), ("teams_hosted", "Teams you already host", "text"),
              ("pitch_line", "One-line pitch to clubs", "text")]
    inputs = []
    for key, label, kind in fields:
        inputs.append(html.Label(label, className="field"))
        if kind == "area":
            inputs.append(dcc.Textarea(id=f"bp-{key}", value=b[key] or "", maxLength=600, style={"minHeight": "64px"}))
        else:
            inputs.append(dcc.Input(id=f"bp-{key}", type=kind, value=b[key], debounce=True, **({"min": 0, "max": 5000, "step": 1} if kind == "number" else {"maxLength": 600})))
    club_cards = []
    for c in clubs:
        home = mk.bar(c["home_bar_id"]) if c["home_bar_id"] else None
        club_cards.append(html.Div(className="rank-card", style={"marginTop": "10px"}, children=[
            html.Div(className="row", children=[html.B(c["name"]), html.Span("demo", className="badge demo") if c["is_demo"] else None]),
            html.Div(f"{c['team']} · usually {c['typical_turnout']} fans · prefers {c['preferred_area']}", className="small muted"),
            html.Div(f"Home bar: {home['name'] if home else 'none yet: open to offers'}", className="small"),
            html.Button("Draft a pitch", id={"type": "pitch-draft", "index": c["id"]}, className="btn btn-ghost btn-sm", style={"marginTop": "8px"},
                        disabled=bool(home and home["id"] == b["id"])),
        ]))
    return html.Div(className="page", children=[
        dcc.Store(id="bar-dash-id", data=b["id"]),
        dcc.Store(id="bar-refresh", data=0),
        dcc.Store(id="pitch-club"),
        html.Div(className="dash-head", children=[
            html.Div(b["name"][:2].upper(), className="avatar"),
            html.Div([html.Div("Bar manager dashboard", className="eyebrow"), html.H1(b["name"], style={"fontSize": "1.9rem", "margin": 0}),
                      html.Div(f"{b['neighborhood']} · {b['city']}", className="muted")], style={"flex": 1}),
            dcc.Link("View public page →", href=f"/bar/{b['id']}", className="btn btn-ghost btn-sm"),
        ]),
        html.Div(className="grid-2", children=[
            html.Div([
                html.Div(className="card", children=[
                    html.Div(className="card-head", children=[html.H3("Your profile"), html.Span("public", className="badge navy")]),
                    html.P("Fan-club presidents see this when they pick a season home bar. We check profile text before it goes live.", className="small muted"),
                    *inputs,
                    html.Button("Save profile", id="bp-save", className="btn btn-navy", style={"marginTop": "12px"}),
                    dcc.Loading(html.Div(id="bp-msg"), type="dot", color="#b8902f"),
                ]),
            ]),
            html.Div([
                html.Div(className="card", children=[
                    html.Div(className="card-head", children=[html.H3("Fan clubs in your city"), html.Span("leads", className="badge gold")]),
                    html.P("Invite a club to make your bar its game-day home. We draft the pitch from your profile, so every promise matches what you actually offer.", className="small muted"),
                    *club_cards,
                ]),
                html.Div(className="card", id="pitch-card", children=[
                    html.H3("Pitch draft"),
                    dcc.Loading(html.Div(id="pitch-status", children=html.Div("Choose “Draft a pitch” on a club above.", className="muted small")), custom_spinner=football_spinner()),
                    html.Label("Subject", className="field"), dcc.Input(id="pitch-subject", type="text", maxLength=200),
                    html.Label("Message", className="field"), dcc.Textarea(id="pitch-body", maxLength=2000, style={"minHeight": "200px"}),
                    html.Button("Send to the club's Home Turf inbox", id="pitch-send", className="btn btn-gold", style={"marginTop": "10px"}),
                    dcc.Loading(html.Div(id="pitch-send-msg"), type="dot", color="#b8902f"),
                ]),
                html.Div(className="card", children=[html.H3("Pitches you've sent"), html.Div(id="bar-pitches")]),
                html.Div(className="card", children=[
                    html.Div(className="card-head", children=[html.H3("Watch parties at your bar"), html.Span("human sign-off", className="badge navy")]),
                    html.Div(id="bar-events"),
                ]),
            ]),
        ]),
    ])


@callback(
    Output("bp-msg", "children"),
    Input("bp-save", "n_clicks"),
    State("bar-dash-id", "data"), State("bp-capacity", "value"), State("bp-tvs", "value"), State("bp-neighborhood", "value"),
    State("bp-sound_policy", "value"), State("bp-specials", "value"), State("bp-teams_hosted", "value"), State("bp-pitch_line", "value"),
    State("session", "data"), prevent_initial_call=True, running=[(Output("bp-save", "disabled"), True, False)],
)
def save_profile(_n, bar_id, capacity, tvs, hood, sound, specials, teams, pitch_line, session):
    def as_int(v):
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return -1
    changes = {"capacity": as_int(capacity), "tvs": as_int(tvs), "neighborhood": (hood or "")[:80], "sound_policy": sound or "",
               "specials": specials or "", "teams_hosted": teams or "", "pitch_line": pitch_line or ""}
    res = mk.update_bar_profile(bar_id, changes, (session or {}).get("sid", "anon"))
    return notice("ok" if res["ok"] else "bad", res["message"])


@callback(
    Output("pitch-status", "children"), Output("pitch-subject", "value"), Output("pitch-body", "value"), Output("pitch-club", "data"),
    Input({"type": "pitch-draft", "index": ALL}, "n_clicks"), State("bar-dash-id", "data"), State("session", "data"),
    prevent_initial_call=True,
)
def draft_pitch(clicks, bar_id, session):
    if not ctx.triggered_id or not any(clicks):
        return no_update, no_update, no_update, no_update
    club_id = ctx.triggered_id["index"]
    run = Run(kind="pitch", session_id=(session or {}).get("sid", "anon"))
    t0 = time.perf_counter()
    try:
        out = write_pitch(run, bar_id, club_id)
    except (BudgetExceeded, AgentError) as exc:
        return [notice("bad", str(exc))], no_update, no_update, no_update
    p = out["pitch"]
    status = [html.Div(f"Draft for {mk.club(club_id)['name']}. Edit freely, then send.", className="small")]
    if out["unsupported_numbers"]:
        status.append(notice("warn", f"Check before sending: these numbers aren't in your profile: {', '.join(out['unsupported_numbers'])}"))
    elif out["retried"]:
        status.append(notice("info", "We fixed a detail that wasn't in your profile."))
    status.append(html.Details([html.Summary("Facts the draft relies on", className="small muted"), html.Ul([html.Li(f, className="small") for f in p["facts_used"]])]))
    status.append(html.Div(receipt(run.totals(), run.steps, time.perf_counter() - t0, title="Pitch Writer run"), style={"marginTop": "8px"}))
    return status, p["subject"], p["body"], club_id


@callback(
    Output("pitch-send-msg", "children"), Output("bar-refresh", "data", allow_duplicate=True),
    Input("pitch-send", "n_clicks"), State("bar-dash-id", "data"), State("pitch-club", "data"), State("pitch-subject", "value"), State("pitch-body", "value"),
    State("session", "data"), State("bar-refresh", "data"), prevent_initial_call=True, running=[(Output("pitch-send", "disabled"), True, False)],
)
def send(_n, bar_id, club_id, subject, body, session, refresh):
    if not club_id or not (body or "").strip():
        return notice("info", "Draft a pitch for a club first."), no_update
    res = mk.send_pitch(bar_id, club_id, (subject or "").strip(), body.strip(), (session or {}).get("sid", "anon"), (session or {}).get("user"))
    return notice("ok" if res["ok"] else "bad", res["message"]), (refresh or 0) + 1


@callback(Output("bar-pitches", "children"), Input("bar-refresh", "data"), State("bar-dash-id", "data"))
def render_pitches(_r, bar_id):
    rows = mk.pitches_from_bar(bar_id)
    if not rows:
        return html.Div("None yet.", className="muted small")
    return [html.Div(className="approval", children=[html.B(r["club_name"]), html.Span(r["subject"], className="small"), html.Div(className="spacer"),
                                                      html.Span(r["status"].replace("_", " "), className="badge confirmed" if r["status"] == "accepted" else "badge navy")]) for r in rows]


@callback(Output("bar-events", "children"), Input("bar-refresh", "data"), State("bar-dash-id", "data"))
def render_events(_r, bar_id):
    return approvals_view(mk.events_for(bar_id=bar_id), lambda e: "bar", "bar-ev")


@callback(
    Output("bar-refresh", "data", allow_duplicate=True),
    Input({"type": "bar-ev-yes", "index": ALL}, "n_clicks"), Input({"type": "bar-ev-no", "index": ALL}, "n_clicks"),
    State("session", "data"), State("bar-refresh", "data"), prevent_initial_call=True,
)
def bar_approve(yes, no, session, refresh):
    if not ctx.triggered_id or not any((yes or []) + (no or [])):
        return no_update
    mk.approve_event(ctx.triggered_id["index"], "bar", (session or {}).get("user"), ctx.triggered_id["type"].endswith("yes"))
    return (refresh or 0) + 1
