"""Central settings for Home Turf: key lookup, model, prices, and budget caps.

The API key is read from the environment, then `<repo>/.env`, then the folder above the
repo (where the teaching staff keep their shared .env). It is never printed or logged.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
DATA_DIR = REPO_DIR / "data"
RUNTIME_DIR = REPO_DIR / "runtime"  # generated at startup, git-ignored
DB_PATH = RUNTIME_DIR / "home_turf.db"
AUDIT_PATH = RUNTIME_DIR / "audit_log.jsonl"

ENV_FILES = (REPO_DIR / ".env", REPO_DIR.parent / ".env")
KEY_NAMES = ("PORTKEY_API_KEY", "OPENAI_API_KEY")

# ---- Model -------------------------------------------------------------------------
# Course key: gpt-6-luna only, through the Portkey gateway, on the Responses API.
MODEL = os.environ.get("HOME_TURF_MODEL", "gpt-6-luna")
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
REQUEST_TIMEOUT_S = 180

# ---- Prices (USD per 1M tokens) ------------------------------------------------------
# gpt-6-luna Standard tier, <=272K context, from https://developers.openai.com/api/docs/pricing
# (checked 2026-10-24). Web search: $10 per 1,000 calls; search content billed as input.
PRICE_INPUT_PER_M = float(os.environ.get("PRICE_INPUT_PER_M", "0.10"))
PRICE_CACHED_INPUT_PER_M = float(os.environ.get("PRICE_CACHED_INPUT_PER_M", "0.01"))
PRICE_CACHE_WRITE_PER_M = float(os.environ.get("PRICE_CACHE_WRITE_PER_M", "0.125"))
PRICE_OUTPUT_PER_M = float(os.environ.get("PRICE_OUTPUT_PER_M", "0.50"))
PRICE_WEB_SEARCH_PER_CALL = float(os.environ.get("PRICE_WEB_SEARCH_PER_CALL", "0.01"))

# ---- Loop limits and spend caps (GUARDRAILS E2, E3) ----------------------------------
MAX_WEB_SEARCHES_PER_SCOUT = 3
MAX_WEB_SEARCHES_WIDE = 4          # second pass, only when the first finds nothing usable
MAX_OUTPUT_TOKENS = 4000
MAX_TOKENS_PER_RUN = 120_000       # one search, one matchmaking run, one pitch
MAX_TOKENS_PER_SESSION = 600_000   # one browser session
MAX_TOKENS_PER_DAY = 3_000_000     # whole app, all users
MAX_RIVALRY_SCOUTS = 2

# ---- Caches (GUARDRAILS E4) ------------------------------------------------------------
SEARCH_CACHE_DAYS = 7
EMPTY_RESULT_CACHE_HOURS = 6
SCHEDULE_CACHE_HOURS = 24

# ---- Input caps (GUARDRAILS S12) -------------------------------------------------------
MAX_QUERY_CHARS = 300
MAX_REVIEW_CHARS = 1500
MAX_PROFILE_FIELD_CHARS = 600
MAX_PAGE_CHARS = 5000

CURRENT_SEASON = 2026

# Operator mode shows run receipts (tokens, cost, agent steps) on every page. Off for the public site;
# the operator console is always at /admin.
SHOW_OPS = os.environ.get("HOME_TURF_OPS", "0") == "1"


class MissingKeyError(RuntimeError):
    pass


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def load_api_key() -> tuple[str, str]:
    """Return (key_name, key). Environment wins, then repo .env, then parent .env."""
    for name in KEY_NAMES:
        if os.environ.get(name):
            return name, os.environ[name]
    for path in ENV_FILES:
        values = _read_env_file(path)
        for name in KEY_NAMES:
            if values.get(name):
                os.environ[name] = values[name]
                return name, values[name]
    raise MissingKeyError(
        "No PORTKEY_API_KEY or OPENAI_API_KEY found. Put a .env file in this folder "
        "or the folder above it (see .env.example)."
    )


def cost_usd(
    input_tokens: int,
    cached_tokens: int,
    output_tokens: int,
    web_searches: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Dollar cost of one model call. Reasoning tokens are already inside output_tokens."""
    uncached = max(input_tokens - cached_tokens - cache_write_tokens, 0)
    return (
        uncached * PRICE_INPUT_PER_M / 1e6
        + cached_tokens * PRICE_CACHED_INPUT_PER_M / 1e6
        + cache_write_tokens * PRICE_CACHE_WRITE_PER_M / 1e6
        + output_tokens * PRICE_OUTPUT_PER_M / 1e6
        + web_searches * PRICE_WEB_SEARCH_PER_CALL
    )
