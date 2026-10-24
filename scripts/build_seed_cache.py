"""Run real searches and schedule lookups once, and save them as seed data.

Graders then get the demo cities instantly with zero tokens, while any new team/city still
runs the live agents. Run:  .venv/bin/python scripts/build_seed_cache.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from agents.schedule import cache_key, get_schedule  # noqa: E402
from core import db  # noqa: E402
from core.budget import Run  # noqa: E402
from core.orchestrator import find_watch_spots  # noqa: E402

SEARCHES = [
    "USC fans in Chicago",
    "Chicago Bears fans in Boston",
    "Yale fans in Chicago",
    "Harvard fans in Chicago",
    "Green Bay Packers fans in Boston",
    "Notre Dame fans in Chicago",
    "Michigan fans in Chicago",
]
TEAMS = ["USC Trojans", "Notre Dame Fighting Irish", "Michigan Wolverines", "Yale Bulldogs",
         "Harvard Crimson", "Chicago Bears", "Green Bay Packers"]


def main() -> None:
    db.init_db()
    for q in SEARCHES:
        r = find_watch_spots(q, session_id="seed-builder")
        t = r["run"].totals()["total"]
        print(f"{q}: ok={r['ok']} groups={len(r.get('groups', []))} tokens={t['input']}+{t['output']} ${t['cost']:.4f}", flush=True)
    for team in TEAMS:
        run = Run(kind="schedule", session_id="seed-builder")
        s = get_schedule(run, team)
        print(f"schedule {team}: {len(s.games) if s else 0} games", flush=True)
    rows = db.query("SELECT key, kind, payload FROM cache")
    entries = [{"key": r["key"], "kind": r["kind"], "payload": json.loads(r["payload"])} for r in rows]
    (config.DATA_DIR / "seed_cache.json").write_text(json.dumps(entries, indent=1, ensure_ascii=False))
    geos = db.query("SELECT address, lat, lon, display, ok FROM geocode_cache")
    (config.DATA_DIR / "seed_geocodes.json").write_text(json.dumps(geos, indent=1, ensure_ascii=False))
    print(f"saved {len(entries)} cache entries and {len(geos)} geocodes")


if __name__ == "__main__":
    main()
