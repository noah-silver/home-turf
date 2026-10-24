"""Landing page."""

from __future__ import annotations

from dash import Input, Output, State, callback, dcc, html, no_update

from core import db
from ui.components import search_href

EXAMPLES = ["USC fans in Chicago", "Chicago Bears fans in Boston", "Harvard vs Yale in Chicago", "Packers fans in Boston", "Michigan fans in Chicago"]


def _stats() -> list[tuple[str, str]]:
    spots = db.one("SELECT COUNT(*) n FROM cache WHERE kind = 'spots'")["n"]
    bars = db.one("SELECT COUNT(*) n FROM bars")["n"]
    clubs = db.one("SELECT COUNT(*) n FROM clubs")["n"]
    runs = db.one("SELECT COUNT(DISTINCT run_id) n, COALESCE(SUM(cost_usd), 0) c FROM usage WHERE run_kind = 'search'")
    avg = (runs["c"] / runs["n"]) if runs["n"] else 0.0
    return [
        (f"{spots}", "team + city searches on file"),
        (f"{bars}", "bar profiles (claimed + found)"),
        (f"{clubs}", "fan clubs on Home Turf"),
        (f"${avg:.3f}" if avg else "≈ $0.02", "average cost of a new search"),
    ]


def layout() -> html.Div:
    pipeline = [
        ("Router", "Understands “USC fans in Chicago”", "no tools"),
        ("Scout", "Searches the web for official club pages and fan lists", "web_search ×3 max"),
        ("Verifier", "Re-opens every source, checks name + season, maps the address", "fetch_page · geocode"),
        ("Matchmaker", "Ranks bars for a club’s season or a rivalry day", "profiles · schedule"),
        ("Guard", "Screens every review, profile, and pitch", "code filter + agent"),
    ]
    steps = []
    for i, (who, what, tool) in enumerate(pipeline):
        steps.append(html.Div(className="pipe-step", children=[html.Div(who, className="who"), html.Div(what, className="what"), html.Span(tool, className="tool")]))
        if i < len(pipeline) - 1:
            steps.append(html.Div("→", className="pipe-arrow"))
    return html.Div(
        className="page",
        children=[
            html.Div(
                className="hero",
                children=[
                    html.Div("Game day, away from home", className="eyebrow"),
                    html.H1(["Find where ", html.Em("your people"), " watch the game, in any city."]),
                    html.P(
                        "Home Turf’s AI agents find the bar where your team’s fan club gathers, verify it against the source, "
                        "and help clubs and bars team up for the whole season, including rivalry days.",
                        className="lead",
                    ),
                    html.Div(
                        className="hero-search",
                        children=[
                            dcc.Input(id="home-q", type="text", placeholder="Try “USC fans in Chicago” or “Bears fans in Boston”", debounce=False, n_submit=0, maxLength=300),
                            html.Button("Find my people", id="home-go", className="btn btn-gold"),
                        ],
                    ),
                    html.Div([dcc.Link(e, href=search_href(e), className="chip") for e in EXAMPLES], className="chips"),
                ],
            ),
            html.Div([html.Div([html.Div(n, className="num"), html.Div(l, className="lbl")], className="stat") for n, l in _stats()], className="stat-strip"),
            html.Div("One app, three kinds of people", className="section-title", style={"marginTop": "40px"}),
            html.Div(
                className="grid-3",
                children=[
                    html.Div(className="card role-card", children=[
                        html.Div("📍", className="icon"), html.H3("Traveling and transplanted fans"),
                        html.P("You’re in Chicago on a Saturday and want to watch USC with other Trojans.", className="muted"),
                        html.Ul([html.Li("Verified watch spots on a map"), html.Li("Sources and evidence for every bar"), html.Li("Game-day reviews from other fans")]),
                        dcc.Link("Find a watch spot →", href="/find", className="btn btn-navy btn-sm"),
                    ]),
                    html.Div(className="card role-card", children=[
                        html.Div("🏈", className="icon"), html.H3("Fan-club presidents"),
                        html.P("You organize 40–120 alumni every game day and cold-call bars each season.", className="muted"),
                        html.Ul([html.Li("Season Matchmaker ranks bars and flags schedule clashes"), html.Li("Rivalry planner drafts a joint watch party"), html.Li("Bars pitch you; you choose")]),
                        dcc.Link("Open the club dashboard →", href="/clubs", className="btn btn-navy btn-sm"),
                    ]),
                    html.Div(className="card role-card", children=[
                        html.Div("🍺", className="icon"), html.H3("Bars"),
                        html.P("A 70-person club on a slow Saturday afternoon is real revenue, every week of the season.", className="muted"),
                        html.Ul([html.Li("Claim your profile and list TVs, sound, specials"), html.Li("Pitch Writer drafts invitations grounded in your profile"), html.Li("Host rivalry days on neutral ground")]),
                        dcc.Link("Open the bar dashboard →", href="/bars", className="btn btn-navy btn-sm"),
                    ]),
                ],
            ),
            html.Div("How the agents work", className="section-title"),
            html.Div(className="card", children=[html.Div(steps, className="pipeline"),
                html.P("Every claim cites a source. The model never writes addresses or map coordinates on its own. Commitments (booking a bar, confirming a watch party) are made only by people.",
                       className="small muted", style={"marginTop": "14px", "marginBottom": 0})]),
            html.Div("Featured rivalry", className="section-title"),
            html.Div(
                className="card",
                style={"background": "linear-gradient(120deg, #fff 60%, #f4ead2)"},
                children=html.Div(className="row", children=[
                    html.Div([
                        html.Div("The Game · Saturday, November 21, 2026", className="eyebrow"),
                        html.H2("Harvard vs. Yale, together in Chicago"),
                        html.P("Two alumni clubs, one neutral bar, three drafted invitations, and nothing happens until all three parties approve.", className="muted"),
                    ], style={"flex": 1}),
                    dcc.Link("Plan it as a club president →", href="/clubs", className="btn btn-gold"),
                ]),
            ),
            html.Div("Home Turf · Yale SOM AI Foundations for Managers final project · Demo profiles are labeled “demo”; watch spots come from live web sources.", className="footer"),
        ],
    )


@callback(
    Output("url", "href", allow_duplicate=True),
    Input("home-go", "n_clicks"),
    Input("home-q", "n_submit"),
    State("home-q", "value"),
    prevent_initial_call=True,
)
def go_search(_clicks, _submit, value):
    if not value or not value.strip():
        return no_update
    return search_href(value.strip()[:300])
