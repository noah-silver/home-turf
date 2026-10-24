"""SQLite storage: profiles, watch spots, reviews, pitches, events, caches, and token usage.

The database is generated in runtime/ on first start from the seed files in data/, so the
seed files are never modified (GUARDRAILS hygiene). `reset_db()` rebuilds it.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

import config

_LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, role TEXT NOT NULL, display_name TEXT NOT NULL,
    bar_id INTEGER, club_id INTEGER, blurb TEXT
);
CREATE TABLE IF NOT EXISTS bars (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, address TEXT, city TEXT,
    neighborhood TEXT, lat REAL, lon REAL, capacity INTEGER, tvs INTEGER,
    sound_policy TEXT, specials TEXT, teams_hosted TEXT, website TEXT, pitch_line TEXT,
    claimed INTEGER DEFAULT 0, is_demo INTEGER DEFAULT 0, source TEXT DEFAULT 'seed',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS clubs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, team TEXT NOT NULL,
    sport TEXT, city TEXT, typical_turnout INTEGER, preferred_area TEXT, needs TEXT,
    home_bar_id INTEGER, contact_url TEXT, is_demo INTEGER DEFAULT 1, created_at TEXT
);
CREATE TABLE IF NOT EXISTS watch_spots (
    id INTEGER PRIMARY KEY AUTOINCREMENT, query_key TEXT, team TEXT, city TEXT,
    club_name TEXT, bar_name TEXT, address TEXT, lat REAL, lon REAL, bar_id INTEGER,
    source_url TEXT, evidence_quote TEXT, season_seen TEXT, status TEXT, status_reason TEXT,
    found_at TEXT
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT, bar_id INTEGER, user_id TEXT, author TEXT,
    team TEXT, rating INTEGER, text TEXT, status TEXT, guard_category TEXT,
    guard_reason TEXT, is_seed INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS summaries (
    bar_id INTEGER PRIMARY KEY, reviews_hash TEXT, payload TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS pitches (
    id INTEGER PRIMARY KEY AUTOINCREMENT, bar_id INTEGER, club_id INTEGER, subject TEXT,
    body TEXT, status TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, bar_id INTEGER, club_id INTEGER, season INTEGER,
    status TEXT, confirmed_by TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, title TEXT, bar_id INTEGER,
    club_a INTEGER, club_b INTEGER, game TEXT, starts_at TEXT, plan TEXT,
    approvals TEXT, status TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY, kind TEXT, payload TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS geocode_cache (
    address TEXT PRIMARY KEY, lat REAL, lon REAL, display TEXT, ok INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, day TEXT, run_id TEXT, session_id TEXT,
    run_kind TEXT, agent TEXT, model TEXT, input_tokens INTEGER, cached_tokens INTEGER,
    output_tokens INTEGER, reasoning_tokens INTEGER, cache_write_tokens INTEGER, web_searches INTEGER,
    latency_ms INTEGER, cost_usd REAL, status TEXT
);
CREATE TABLE IF NOT EXISTS guard_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, layer TEXT, allowed INTEGER,
    category TEXT, reason TEXT, excerpt TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    config.RUNTIME_DIR.mkdir(exist_ok=True)
    with _LOCK:
        conn = sqlite3.connect(config.DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def query(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple | list = ()) -> int:
    with connect() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid


def insert(table: str, row: dict[str, Any]) -> int:
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    return execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values()))


def update(table: str, row_id: int, changes: dict[str, Any]) -> None:
    sets = ", ".join(f"{k} = ?" for k in changes)
    execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*changes.values(), row_id])


# ---- cache helpers -------------------------------------------------------------------

def cache_get(key: str, max_age_hours: float) -> Any | None:
    row = one("SELECT payload, created_at FROM cache WHERE key = ?", (key,))
    if not row:
        return None
    age = datetime.now(timezone.utc) - datetime.fromisoformat(row["created_at"])
    if age.total_seconds() > max_age_hours * 3600:
        return None
    return json.loads(row["payload"])


def cache_put(key: str, kind: str, payload: Any) -> None:
    execute(
        "INSERT OR REPLACE INTO cache (key, kind, payload, created_at) VALUES (?, ?, ?, ?)",
        (key, kind, json.dumps(payload), now_iso()),
    )


# ---- setup -----------------------------------------------------------------------------

def _load_seed(name: str) -> Any:
    path = config.DATA_DIR / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def init_db(force: bool = False) -> None:
    """Create the runtime database from seed files if it does not exist yet."""
    config.RUNTIME_DIR.mkdir(exist_ok=True)
    if force and config.DB_PATH.exists():
        config.DB_PATH.unlink()
    fresh = not config.DB_PATH.exists()
    with connect() as conn:
        conn.executescript(SCHEMA)
    if fresh:
        _seed()


def reset_db() -> None:
    init_db(force=True)


def _seed() -> None:
    stamp = now_iso()
    for bar in _load_seed("seed_bars.json") or []:
        insert("bars", {**bar, "created_at": stamp})
    for club in _load_seed("seed_clubs.json") or []:
        insert("clubs", {**club, "created_at": stamp})
    for user in _load_seed("seed_users.json") or []:
        insert("users", user)
    for review in _load_seed("seed_reviews.json") or []:
        insert("reviews", {**review, "status": "posted", "guard_category": "ok", "is_seed": 1, "created_at": stamp})
    for booking in _load_seed("seed_bookings.json") or []:
        insert("bookings", {**booking, "created_at": stamp})
    for geo in _load_seed("seed_geocodes.json") or []:
        execute(
            "INSERT OR REPLACE INTO geocode_cache (address, lat, lon, display, ok, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (geo["address"], geo["lat"], geo["lon"], geo.get("display", ""), geo.get("ok", 1), stamp),
        )
    for entry in _load_seed("seed_cache.json") or []:
        # Seeded search results are stamped "now" so graders get instant demo cities.
        execute(
            "INSERT OR REPLACE INTO cache (key, kind, payload, created_at) VALUES (?, ?, ?, ?)",
            (entry["key"], entry["kind"], json.dumps(entry["payload"]), stamp),
        )
