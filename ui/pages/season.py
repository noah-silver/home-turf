"""My Season: pick your team, say where you'll be, and get a game-by-game plan of where to watch."""

from __future__ import annotations

import time

from dash import Input, Output, State, callback, dcc, html, no_update

import config
from agents.llm import AgentError
from agents.schedule import get_schedule
from agents.season_planner import kickoff_local, plan_season, save_plan, to_ics
from core import marketplace as mk
from core.budget import BudgetExceeded, Run
from ui.components import notice, receipt
from ui.fun import football_spinner
from ui.team_logos import _teams, lookup

LEAGUE_SPORT = {"NFL": "NFL", "college": "college football", "NBA": "NBA", "MLB": "MLB", "NHL": "NHL", "WNBA": "WNBA"}
EXAMPLE = "Home in New Haven most weekends. I'm in New York for the Columbia game, and in Chicago with family the week of The Game."


def _team_options() -> list[dict]:
    seen, out = set(), []
    for t in sorted(_teams(), key=lambda t: (t["league"] not in ("NFL", "college"), t["name"])):
        if t["name"] in seen:
            continue
        seen.add(t["name"])
        out.append({"label": f"{t['name']} ({'NCAA' if t['league'] == 'college' else t['league']})", "value": t["name"]})
    return out


def _logo(team: str, size: int = 40):
    t = lookup(team)
    if t["logo"]:
        return html.Img(src=t["logo"], className="team-logo", style={"width": f"{size}px", "height": f"{size}px"})
    return html.Span(t["abbr"], className="team-mono", style={"width": f"{size}px", "height": f"{size}px", "lineHeight": f"{size}px", "background": t["color"]})


def layout(session: dict | None) -> html.Div:
    user = mk.user((session or {}).get("user"))
    team = (user or {}).get("favorite_team") or "Yale Bulldogs"
    home = (user or {}).get("home_city") or "New Haven, CT"
    return html.Div(className="page", children=[
        dcc.Store(id="season-plan"),
        dcc.Download(id="season-ics"),
        html.Div(className="dash-head", children=[
            html.Div(id="season-team-logo", children=_logo(team, 46), className="avatar", style={"background": "#fff"}),
            html.Div([html.Div("My season", className="eyebrow"), html.H1("Plan where you'll watch every game", style={"margin": 0}),
                      html.Div("Pick your team, tell us where you'll be, and we'll line up a bar for every game, in whatever city you're in.", className="muted")]),
        ]),
        html.Div(className="grid-2", children=[
            html.Div([
                html.Div(className="card", children=[
                    html.Label("Your team", className="field"),
                    dcc.Dropdown(id="season-team", options=_team_options(), value=team, clearable=False, searchable=True),
                    html.Label("Where will you be?", className="field"),
                    dcc.Textarea(id="season-trip", placeholder=EXAMPLE, maxLength=1500, style={"minHeight": "110px"}),
                    html.Div(className="row", style={"marginTop": "6px"}, children=[
                        html.Span("Default city (when you don't say):", className="small muted"),
                        dcc.Input(id="season-home", type="text", value=home, style={"flex": 1}, maxLength=80),
                    ]),
                    html.Div(className="row", style={"marginTop": "12px"}, children=[
                        html.Button("Build my game-day plan", id="season-go", className="btn btn-gold"),
                        html.Button("Use example", id="season-example", className="btn btn-ghost btn-sm"),
                    ]),
                ]),
                html.Div(className="card", children=[html.H3("The schedule"), dcc.Loading(html.Div(id="season-schedule"), custom_spinner=football_spinner())]),
            ]),
            html.Div(className="card", children=[
                html.Div(className="card-head", children=[html.H3("Your game-day plan"), html.Button("Add to my calendar (.ics)", id="season-ics-btn", className="btn btn-ghost btn-sm")]),
                dcc.Loading(html.Div(id="season-out", children=html.Div("Your plan shows up here: a bar for every game, with local kickoff times.", className="muted")),
                            custom_spinner=football_spinner()),
            ]),
        ]),
    ])


@callback(Output("season-trip", "value"), Input("season-example", "n_clicks"), prevent_initial_call=True)
def example(_n):
    return EXAMPLE


@callback(Output("season-schedule", "children"), Output("season-team-logo", "children"),
          Input("season-team", "value"), Input("season-home", "value"), State("session", "data"))
def show_schedule(team, home, session):
    if not team:
        return no_update, no_update
    run = Run(kind="schedule", session_id=(session or {}).get("sid", "anon"))
    try:
        sched = get_schedule(run, team)
    except (BudgetExceeded, AgentError) as exc:
        return notice("bad", str(exc)), _logo(team, 46)
    if not sched or not sched.games:
        return notice("info", f"Couldn't find a {config.CURRENT_SEASON} schedule for {team} yet."), _logo(team, 46)
    rows = []
    for g in sched.games:
        _, label = kickoff_local(g.date, g.kickoff_et, home)
        rows.append(html.Div(className="sched-row", children=[
            html.Div(g.date[5:].replace("-", "/"), className="sched-date"),
            html.Span("vs" if g.home_away == "home" else ("at" if g.home_away == "away" else "·"), className="tiny muted"),
            _logo(g.opponent, 24), html.B(g.opponent), html.Div(className="spacer"),
            html.Span(label, className="small muted"), html.Span(g.tv, className="badge navy"),
        ]))
    return [html.Div(rows), html.Div(["Times shown for ", html.B(home or "Eastern"), " · ", html.A("source", href=sched.source_url, target="_blank")], className="tiny muted", style={"marginTop": "8px"})], _logo(team, 46)


def _plan_view(plan: dict) -> list:
    cards = []
    for g in plan["games"]:
        pick, backup = g.get("pick"), g.get("backup")
        status = (pick or {}).get("status", "")
        ring = {"confirmed": "#1f7a4d", "likely": "#b7791f", "Home Turf partner": "#b8902f", "shows every game": "#2f6db3"}.get(status, "#8a94a6")
        cards.append(html.Div(className="plan-card", style={"borderLeftColor": ring}, children=[
            html.Div(className="plan-date", children=[html.Div(g["date"][5:7] + "/" + g["date"][8:], className="pd-day"), html.Div(g["kickoff_local"], className="pd-time")]),
            html.Div(style={"flex": 1}, children=[
                html.Div(className="row", style={"gap": "8px"}, children=[_logo(g["opponent"], 22), html.B(("vs " if g["home_away"] == "home" else "at ") + g["opponent"]),
                                                                          html.Span(f"📍 {(g['city'] or 'city not set').split(',')[0]}", className="badge gold")]),
                html.Div(className="plan-pick", children=(
                    [html.Span("Watch at "), dcc.Link(pick["bar"], href=f"/bar/{pick['bar_id']}") if pick.get("bar_id") else html.B(pick["bar"]),
                     html.Span(f" · {status}", className="tiny muted")] if pick else [html.Span("No known spot yet. Try a search for this city, or add one.", className="muted")])),
                html.Div(f"Backup: {backup['bar']}", className="tiny muted") if backup else None,
                html.Div(g.get("tip", ""), className="small", style={"marginTop": "4px"}),
            ]),
        ]))
    extra = [notice("info", f"Not searched yet (limit {4} new cities per plan): {', '.join(plan['skipped_cities'])}. Build again to cover them.")] if plan.get("skipped_cities") else []
    return [html.P(plan["summary"], style={"fontWeight": 600}), *extra, html.Div(cards, className="plan-list")]


@callback(Output("season-out", "children"), Output("season-plan", "data"),
          Input("season-go", "n_clicks"), State("season-team", "value"), State("season-trip", "value"), State("season-home", "value"), State("session", "data"),
          prevent_initial_call=True, running=[(Output("season-go", "disabled"), True, False)])
def build(_n, team, trip, home, session):
    sid = (session or {}).get("sid", "anon")
    run = Run(kind="season_plan", session_id=sid)
    t0 = time.perf_counter()
    sport = LEAGUE_SPORT.get(lookup(team)["league"], "soccer")
    try:
        plan = plan_season(run, team, sport, trip or "", (home or "").strip() or None)
    except (BudgetExceeded, AgentError) as exc:
        return notice("bad", str(exc)), no_update
    if "error" in plan:
        return notice("info", plan["error"]), no_update
    save_plan((session or {}).get("user"), team, trip or "", plan)
    view = _plan_view(plan) + [html.Div(receipt(run.totals(), run.steps, time.perf_counter() - t0, title="Season plan run"), style={"marginTop": "10px"})]
    return [html.Div("🎉", className="celebrate", style={"display": "none"}), *view], plan


@callback(Output("season-ics", "data"), Input("season-ics-btn", "n_clicks"), State("season-plan", "data"), prevent_initial_call=True)
def download(_n, plan):
    if not plan:
        return no_update
    name = plan["team"].lower().replace(" ", "-")
    return {"content": to_ics(plan), "filename": f"home-turf-{name}-season.ics", "type": "text/calendar"}
