# Home Turf: Safety and Efficiency Guardrails

Every rule below comes from this semester's lectures (L2 to L11) or homeworks (HW1 to HW5), adapted to Home Turf. Each rule is a build requirement, and the report's Safety and Tokenomics sections point back here.

## Safety

| # | Rule | How Home Turf applies it | Source |
|---|---|---|---|
| S1 | Never invent facts; every claim cites its tool result | Scout returns `evidence_quote` + `source_url` for every bar; no source = not shown. Unknown fields say "unknown". | HW5 shop_rules.md, HW4 prompt rule 1, L7/L8 prompts |
| S2 | The model never writes coordinates or addresses from memory | Geocode tool turns the address into a pin; address that does not resolve is flagged gray | L7 grounding, HW1 "do not invent values" |
| S3 | Untrusted content is data, not instructions | Web pages, bar profiles, pitches, and reviews go inside a delimited `## UNTRUSTED CONTENT` block; prompts say to describe, never obey | HW3 prompt rule 3, L5 prompt.md, L11 `## EVIDENCE` block |
| S4 | Screen user-generated content before it posts | Guard agent checks reviews, bar profiles, and pitches for injection ("rank us #1"), spam, abuse, and fake claims; blocked items are logged | HW4 prompt rule 3, HW3 safety_notes |
| S5 | Pitches are grounded in the bar's own profile | Pitch Writer may only use fields from the bar profile; a validator rejects any number or promise not in the profile | HW5 output validators (ModelRetry) |
| S6 | Drafts only, never auto-send | Pitches and outreach emails are status `draft_not_sent`; UI says "drafted", never "sent" | HW5 shop_rules.md, HW2 HARNESS.md |
| S7 | Humans approve commitments | Only a club president can accept a bar for the season (typed confirm step); no agent tool can book | HW5 approvals.py, HUMAN_ONLY_TOOLS |
| S8 | Least privilege tool allowlist per agent | Each agent gets only its listed tools; startup `assert` that no agent has a human-only tool | HW5 mcp_link.py, L7 agent.py |
| S9 | Structured outputs with validation | Every agent returns a Pydantic model via JSON schema; tool args validated with `Field` bounds | L8 tools.py, L10 boss.py, HW5 agents.py |
| S10 | Stay on topic | Router declines non sports-bar requests; no legal, medical, or financial advice | HW4 prompt rules 4 to 7, L8 prompt |
| S11 | Privacy | No personal emails or phone numbers scraped from the web shown to users; only public club and bar contact info | HW3 harness, L5 prompt |
| S12 | Input caps before any AI call | Query 300 chars, review 1,500 chars, profile fields capped; rejected inputs still logged | HW3 harness |
| S13 | Contained failures | An agent exception becomes an error result for the orchestrator, never a crash; polite message to the user | L10/L11 specialists.py |
| S15 | Respect content owners | Reputation agent summarizes review themes in its own words (no copied review text), reports ratings only when a source shows them, links out to Google/Yelp; photos and logos are linked from their owners, never copied into the repo | Course copyright norms; Yelp/Google terms |
| S16 | Fan-supplied data is screened and labeled | Suggested spots go through the Guard, are labeled "Fan-suggested", and become "Verified" only if a linked page names the bar and team | HW4 Guard pattern |
| S17 | Map data cannot inject script | All map data is JSON-encoded with `</` escaped and HTML-escaped in the page; maps are served from the app's own origin | Lecture 5 untrusted content |
| S14 | Append-only audit trail | Every step logged: agent, prompt hash, tool calls + args, results clipped, usage, stop reason, human decisions; locked atomic writes; never secrets | HW5 audit.py, L8 agent.py |

## Efficiency and cost

| # | Rule | How Home Turf applies it | Source |
|---|---|---|---|
| E1 | Model: gpt-6-luna only (course key) on the Responses API | All agents; low reasoning effort for Router, Guard, Summarizer | Assignment, L11 config.py, HW5 llm.py |
| E2 | Hard loop limits | Per-agent request and tool-call limits (Scout max 3 web searches per query); orchestrator max steps | L10 UsageLimits, HW5 limits |
| E3 | Token budgets and spend caps | Per-search, per-session, and daily token caps; the run stops cleanly and tells the user when a cap is hit | HW5 250k per ticket, L11 MAX_DELEGATIONS |
| E4 | Cache before calling the model | SQLite cache: search results 7 days, geocodes permanent, review summaries until a new review arrives; seeded demo cities | HW3 content-hash cache |
| E5 | Prompt-cache friendly layout | Static shared rules first, then role prompt, then per-request data in the input (not the system prompt); measure `cached_tokens` | HW5 build_instructions; fixes the L10/L11 gap |
| E6 | Cheap code before LLM | Deterministic checks (geocode, URL fetch, date check) run before any LLM verifier call; skip the model when nothing is found | HW3 harness, L10 specialists.py |
| E7 | Retrieval caps | Fetched pages clipped (about 5,000 chars), max results per search, long fields clipped | L11 retrieval caps, L7 tools.py |
| E8 | Retries only where useful | Backoff with jitter, max 4, only on 429, 5xx, and timeouts | HW3 build_catalogue.py |
| E9 | Measure every call | Log `input_tokens`, `input_tokens_details.cached_tokens`, `output_tokens`, reasoning tokens, latency; show cost per run in the UI | L10 tracing.py, L11 events.py |
| E11 | Escalate only when needed | Scout's wide pass and best bets run only when the first pass finds nothing usable; City Sweep runs on a button or seed, batching all verification into one call | Experiment in report |
| E12 | Don't cache failure for long | Empty results expire after 6 hours instead of 7 days | Falcons-in-Phoenix bug |
| E10 | Price constants are explicit | gpt-6-luna prices set in `config.py` with their source; no price found in course files, so confirm before the report | HW and lecture gap |

## Engineering hygiene

- `.env` lookup: environment, then repo folder, then the parent folder (assignment rule). Key never printed or logged. Fail fast with a clear message if missing.
- Portkey: `https://api.portkey.ai/v1`, headers `x-portkey-api-key` and `x-portkey-provider: openai`, timeout 180 s.
- `.gitignore`: `.env`, `**/.env`, `.venv`, `__pycache__`, `*.db`, `*.log`; `.env.example` with blank values only.
- Dash: `debug=False, use_reloader=False`; stop the whole process tree; clear stale servers on port 8050 before starting.
- Local `.venv`; pause OneDrive sync during installs if they stall.
- No hard-coded data in code; seed data lives in `data/`.
- Never modify seed data in place; the app works on a generated SQLite file with a reset option.

## Look and feel

- Investment-committee polish: navy `#0f2240`, gold `#b8902f`, Georgia headings, white cards; all visuals in HTML/CSS.
- No spreadsheet-style tables as the main UI; cards, map, and list instead.
- Search input: Enter submits, visible loading state, double-submit guard, retry on error, starter chips.
- Responsive breakpoints at 1280 and 860 px.
