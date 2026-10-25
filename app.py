"""Home Turf web app. Run:  python app.py   then open http://127.0.0.1:8050

Dash runs with debug=False and no reloader so one process serves the app (see AGENTS.md rules).
"""

from __future__ import annotations

import os
import uuid

from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update

import config
from core import db

db.init_db()

from ui.components import topbar  # noqa: E402  (pages import the database on load)
from ui.pages import bar as bar_page  # noqa: E402
from ui.pages import bars as bars_page  # noqa: E402
from ui.pages import clubs as clubs_page  # noqa: E402
from ui.pages import console as console_page  # noqa: E402
from ui.pages import find as find_page  # noqa: E402
from ui.pages import home as home_page  # noqa: E402
from ui.pages import season as season_page  # noqa: E402

FONTS = "https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;500;600;700;800&display=swap"
app = Dash(__name__, title="Home Turf · find your fans on game day", suppress_callback_exceptions=True, update_title=None,
           external_stylesheets=[FONTS])
server = app.server


@server.route("/mapframe/<token>")
def mapframe(token: str):
    from flask import Response

    from ui.logo_map import get_frame

    page = get_frame(token)
    if page is None:
        return Response("Map expired. Reload the page.", status=404, mimetype="text/plain")
    return Response(page, mimetype="text/html")

DEFAULT_USER = "fan_jordan"  # visitors start as a Yale fan in New Haven (switch any time in Demo login)


def serve_layout() -> html.Div:
    # A browser tab keeps its stored session; a new tab gets a fresh session id.
    return html.Div([
        dcc.Location(id="url", refresh="callback-nav"),
        dcc.Store(id="session", storage_type="session", data={"sid": uuid.uuid4().hex[:12], "user": DEFAULT_USER}),
        dcc.Store(id="page-user", data="__none__"),
        html.Div(id="topbar-slot"),
        html.Div(id="page"),
        # Bar quick-view: opens a bar's full profile over any dashboard without leaving it.
        html.Div(id="bar-modal", className="modal hidden", children=html.Div(className="modal-box", children=[
            html.Div(className="modal-head", children=[html.Span("Bar profile", className="eyebrow"), html.Div(className="spacer"),
                                                       html.A("Open full page ↗", id="bar-modal-link", href="#", target="_blank", className="btn btn-ghost btn-sm"),
                                                       html.Button("✕ Close", id="bar-modal-close", className="btn btn-navy btn-sm")]),
            html.Iframe(id="bar-modal-frame", src="about:blank", className="modal-frame"),
        ])),
    ])


app.layout = serve_layout


@app.callback(Output("topbar-slot", "children"), Input("url", "pathname"), State("session", "data"), State("url", "search"))
def render_topbar(path, session, search):
    from ui.fun import ticker

    if "embed=1" in (search or ""):
        return None  # bar quick-view inside a pop-up: no nav bar
    bar = topbar(path or "/")
    user = (session or {}).get("user")
    bar.children.children[2].children[1].value = user or "guest"
    return [bar, ticker()]


@app.callback(Output("session", "data", allow_duplicate=True), Input("login-dd", "value"), State("session", "data"), prevent_initial_call=True)
def login(value, session):
    session = dict(session or {"sid": uuid.uuid4().hex[:12]})
    new_user = None if value in (None, "guest") else value
    if session.get("user") == new_user:
        return no_update
    session["user"] = new_user
    return session


@app.callback(
    Output("page", "children"), Output("page-user", "data"),
    Input("url", "pathname"), Input("session", "data"), State("url", "search"), State("page-user", "data"),
)
def route(path, session, search, page_user):
    user = (session or {}).get("user") or "guest"
    if ctx.triggered_id == "session" and user == page_user:
        return no_update, no_update  # session refreshed but the logged-in user did not change
    return _render(path or "/", session, search), user


def _render(path, session, search):
    if path == "/find":
        return find_page.layout(search)
    if path.startswith("/bar/"):
        try:
            return bar_page.layout(int(path.split("/")[2]), session)
        except ValueError:
            pass
    if path == "/season":
        return season_page.layout(session)
    if path == "/clubs":
        return clubs_page.layout(session)
    if path == "/bars":
        return bars_page.layout(session)
    if path in ("/admin", "/console"):  # operator console: not linked from the public site
        return console_page.layout(session)
    return home_page.layout()


@app.callback(
    Output("bar-modal", "className"), Output("bar-modal-frame", "src"), Output("bar-modal-link", "href"),
    Input({"type": "view-bar", "index": ALL}, "n_clicks"), Input("bar-modal-close", "n_clicks"),
    prevent_initial_call=True,
)
def bar_modal(clicks, _close):
    if ctx.triggered_id == "bar-modal-close" or not ctx.triggered_id or not any(clicks or []):
        return "modal hidden", "about:blank", "#"
    bar_id = ctx.triggered_id["index"]
    return "modal", f"/bar/{bar_id}?embed=1", f"/bar/{bar_id}"


if __name__ == "__main__":
    try:
        config.load_api_key()
    except config.MissingKeyError as exc:
        print(f"\n  ⚠  {exc}\n  The app will start, and cached demo searches work, but new AI calls will fail.\n")
    port = int(os.environ.get("PORT", "8050"))
    print(f"\n  Home Turf is running at http://127.0.0.1:{port}\n")
    app.run(debug=False, use_reloader=False, host="127.0.0.1", port=port)
