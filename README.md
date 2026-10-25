# Home Turf

**Find where your team's fan club watches the game in any city, verified against the source. Help fan clubs and bars team up for the season, rivalry days included.**

Home Turf is a multi-agent web app with three kinds of users:

- **Fans**: search "Yale fans in Chicago" and get verified watch spots on a map of **team logos**, with sources, evidence quotes, photos, public review summaries, and game-day reviews. Search just "Boston" to see every team's fans in the city, filter the map by league, and plan a whole season: tell the agent where you'll be and get a bar for every game.
- **Fan-club presidents**: the Season Matchmaker ranks bars for the club's season and flags schedule clashes. The rivalry planner drafts a joint watch party, for example Yale vs. Princeton in New York.
- **Bars**: claim a profile, then let the Pitch Writer draft invitations to clubs, grounded only in what the bar's profile says.

Built for Yale SOM *AI Foundations for Managers* (final project, fall 2026) by Noah Silver. Model: `gpt-6-luna` via Portkey (the course key).

![Find page](docs/screenshots/find_usc_chicago.png)

---

## Run it (about 5 minutes)

You need **Python 3.11 or newer** and an internet connection. The API key is read from a `.env` file **in this folder or the folder above it**, so the teaching staff's shared `submissions/.env` works as is.

**macOS / Linux**

```bash
git clone https://github.com/noah-silver/home-turf.git
cd home-turf
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

**Windows (PowerShell)**

```powershell
git clone https://github.com/noah-silver/home-turf.git
cd home-turf
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:8050**.

**API key:** if there is no `.env` in this folder or the one above, copy `.env.example` to `.env` and fill in `PORTKEY_API_KEY` (or `OPENAI_API_KEY`). Without a key the app still opens, and the seeded demo searches load from cache, but new AI calls fail with a clear message.

**Operator mode:** the public site hides costs and agent details. Start with `HOME_TURF_OPS=1 python app.py` to show a token/cost receipt under every result; the operator console is always at http://127.0.0.1:8050/admin.

The first start creates `runtime/home_turf.db` from the seed files in `data/`. To reset all demo data, use the **Reset demo data** button on the *Cost & safety* page, or delete the `runtime/` folder.

---

## A 5-minute tour

You start logged in as **Jordan, a Yale fan in New Haven**. Switch roles any time under **Demo login** (top right).

1. **Home → "New Haven" or "Chicago" chip**: every team with a known fan spot in the city, as logo pins. Filter with the league buttons on the map (NFL, NCAA, MLB, NBA, NHL, Soccer) and click a logo for the bar's popup.
2. **"Yale fans in Chicago"** (chip): cached, so instant. Piece Brewery and Pizzeria, *Verified*, from the Yale Club of Chicago's own page.
3. **A new search**, e.g. "Seahawks fans in Denver": runs live in a few seconds. Router → Scout (web search) → Verifier (re-opens each source, checks the bar's name and the season, places the address). If nothing team-specific exists ("Falcons fans in Phoenix"), a wider pass finds the fan club chapter and verified bars that show every game, and fans can add a spot.
4. **"Bar page, photos & reviews"** on a real bar: public rating and review themes in the agent's own words, photos from the bar's own site, and an embedded Google Maps card.
5. **My season** (nav): Yale is preselected. *Use example* → *Build my game-day plan* gives a bar, backup, and local kickoff for every remaining game in the cities you'll be in. *Add to my calendar (.ics)* exports it.
6. **Demo login → "Chris Park · Yale Club of NYC Football Watch"** → *For fan clubs*:
   - **Find our season home bar** ranks New York bars for the club and flags clashes with other clubs' games.
   - **Plan rivalry watch party** (Princeton preselected) finds Yale–Princeton (Nov 14), picks a neutral bar that holds both clubs, and drafts three invitations. Click **Propose**. (USC vs. UCLA in Chicago works the same way.)
7. **Demo login → the recommended bar's manager** (e.g. "Leo Grant · Brooklyn Bullpen" or "Rosa Diaz · Midtown Tailgate") → *For bars*: approve the watch party, **Draft a pitch** to a club, and try adding "$1 beers" before sending; the number check blocks it.
8. **Demo login → "Hannah Kim · Princeton Tigers of NYC"** → approve. The party is *confirmed* only after all three people approve.
9. **Operator console** at http://127.0.0.1:8050/admin (not linked from the site): spend per agent, budget meters, cache savings, Guard decisions, the audit trail, and a "Try to break it" box for prompt-injection tests.

All demo clubs, bars, people, and seed reviews are fictional and labeled **demo**. Watch spots in search results are real, from live web sources.

---

## How it works

| Agent | Job | Tools |
|---|---|---|
| Router | Turns a search into `{intent, team, city}`; declines off-topic or unsafe requests | none (structured output) |
| Scout | Finds where fans or the official club watch, with source URLs and quoted evidence. If nothing usable, a wide second pass (metro area, fan club directories) also returns verified "shows every game" best bets | `web_search` (max 3, then max 4) |
| City Sweep | Maps many teams' fan bars in one city at once (NFL, college, other leagues) so the city map shows every logo | `web_search` (max 4 per league group) |
| Reputation | A real bar's public ratings and review themes, summarized in its own words (no copying), plus photos from the bar's own site | `web_search` (max 2), `site_photos` |
| Trip Parser | Turns "Boston until Nov 10, then Chicago" into a city for each game date | none |
| Season Planner | A bar, backup, local kickoff, and tip for every game; calendar export | cached spots, Scout for new cities (max 4 per plan) |
| Verifier | Re-checks each candidate. Code checks first; the model only for unclear cases | `fetch_page`, `geocode` |
| Schedule | A team's season schedule (cached 24 h) | `web_search` (max 2) |
| Matchmaker | Season mode (club → home bar) and rivalry mode (two clubs → one bar, one game) | profiles, schedules, computed conflicts |
| Pitch Writer | A bar's invitation to a club, grounded only in the bar's profile | profile facts, number validator |
| Guard | Screens reviews, bar profiles, and pitches before they post | free code filter, then the model |
| Summarizer | Turns reviews into a game-day score (cached until a new review arrives) | none |

The model never writes map coordinates (a geocoder places the pins). No agent can book a bar, send a message, or approve an event; people do that in the app. Every model call is logged with its input, cached, output, and reasoning tokens, web searches, latency, and cost. See [`docs/GUARDRAILS.md`](docs/GUARDRAILS.md) for the full list of safety and cost rules and where each one is enforced.

```
home-turf/
├── app.py                 Dash entry point (debug off, no reloader)
├── config.py              key lookup (env → ./.env → ../.env), model, prices, caps
├── agents/                router, scout, verifier, schedule, matchmaker, pitch_writer, guard, summarizer
│   ├── llm.py             the one doorway to the model: caps, retries, structured output, usage + audit logging
│   └── prompts/           shared_rules.md + one prompt per agent
├── tools/                 geocode.py (OpenStreetMap Nominatim, no key), fetch_page.py (public URLs only, site photos)
├── core/                  orchestrator, database, budget caps, audit trail, marketplace actions
├── ui/                    pages: home, find, bar, clubs, bars, console; logo_map.py (MapLibre logo map), team_logos.py, fun.py (ticker, logo wall)
├── mcp_server/server.py   optional MCP server (read-only + drafts)
├── data/                  seed profiles, reviews, and a cache of real searches for instant demos
├── tests/test_safety.py   24 safety, cost-control, and feature tests
├── scripts/               measure_tokens.py, build_seed_cache.py, mcp_smoke_test.py
└── docs/                  GUARDRAILS.md, measurements.json, screenshots, report.html, slides.html
```

## Tests

```bash
python -m unittest -v tests.test_safety                      # 21 offline tests, no API cost
HOME_TURF_LIVE=1 python -m unittest -v tests.test_safety     # + 3 live tests (~$0.001)
```

## Optional: MCP server

Lets an AI assistant (Claude Desktop, ChatGPT, Claude Code) use Home Turf's tools: `find_watch_spots_tool`, `get_bar_profile`, `list_fan_clubs`, and `draft_rivalry_watch_party`. They are read-only or drafts only.

```bash
pip install -r requirements-mcp.txt
python scripts/mcp_smoke_test.py          # starts the server over stdio and calls two tools
```

Client config: command `<path>/.venv/bin/python`, args `["<path>/mcp_server/server.py"]`, with `PORTKEY_API_KEY` in its environment or a `.env` as above.

## Data and costs

- **Seed data** (`data/`): 8 demo bars, 7 demo clubs, 9 demo logins, 13 seed reviews, plus cached real searches, City Sweeps of Boston, Chicago, New York, Phoenix, and New Haven, and 7 team schedules (built with `scripts/build_seed_cache.py`), so the demo maps are full from the first click.
- **Team logos** (`data/team_logos.json`, built by `scripts/build_team_logos.py` from ESPN's public team lists): about 1,000 NFL, college, MLB, NBA, NHL, WNBA, and soccer teams. Logos are linked, not copied.
- **Reviews and photos**: Yelp's and Google's APIs need extra keys that this project can't require, and their terms forbid scraping. So review themes are summarized from public pages with links out, photos come from each bar's own website, and the Google Maps place card is Google's official embed.
- **Live data**: any new team and city runs the agents against the live web.
- **Cost**: a new search costs about 1–2 cents (mostly the $0.01 web-search fee). A cached search costs $0. Matchmaking, pitches, and Guard checks cost fractions of a cent. Measured numbers are in `docs/measurements.json` and the report.
- **Caps**: 120k tokens per action, 600k per browser session, 3M per day for the whole app.
