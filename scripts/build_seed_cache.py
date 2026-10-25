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

config.DB_PATH = config.RUNTIME_DIR / "seed_build.db"  # build in a separate database
from agents.schedule import cache_key, get_schedule  # noqa: E402
from core import db  # noqa: E402
from core.budget import Run  # noqa: E402
from core.orchestrator import find_watch_spots  # noqa: E402

SWEEP_CITIES = ["Boston, MA", "Chicago, IL", "New York, NY", "Phoenix, AZ", "New Haven, CT"]
SEARCHES = [
    "USC fans in Chicago",
    "Chicago Bears fans in Boston",
    "Yale fans in Chicago",
    "Harvard fans in Chicago",
    "Green Bay Packers fans in Boston",
    "Notre Dame fans in Chicago",
    "Michigan fans in Chicago",
    "Atlanta Falcons fans in Phoenix",
    "Pittsburgh Steelers fans in Denver",
    "UCLA fans in Chicago",
    "Ohio State fans in Chicago",
    "Liverpool fans in Chicago",
    "Manchester United fans in Chicago",
    "New York Yankees fans in Boston",
    "New York Knicks fans in Boston",
    "New England Patriots fans in New York",
    "Buffalo Bills fans in New York",
    "Boston Bruins fans in New York",
    "Boston Red Sox fans in New York",
    "USC fans in Boston",
    "USC fans in Phoenix",
    "Yale fans in New York",
    "Yale fans in Boston",
    "Princeton fans in New York",
    "Yale fans in New Haven",
]
TEAMS = ["USC Trojans", "Notre Dame Fighting Irish", "Michigan Wolverines", "Yale Bulldogs", "Harvard Crimson",
         "Chicago Bears", "Green Bay Packers", "UCLA Bruins", "Ohio State Buckeyes", "Liverpool", "Manchester United",
         "New York Yankees", "New York Knicks", "New England Patriots", "Buffalo Bills", "Boston Bruins", "Boston Red Sox", "Princeton Tigers"]


def main() -> None:
    from agents.city_sweep import city_sweep, recently_swept

    db.reset_db()  # starts from the current seed files, so earlier results are reused, not re-bought
    for q in SEARCHES:
        r = find_watch_spots(q, session_id="seed-builder")
        t = r["run"].totals()["total"]
        print(f"{q}: ok={r['ok']} groups={len(r.get('groups', []))} tokens={t['input']}+{t['output']} ${t['cost']:.4f}", flush=True)
    for team in TEAMS:
        run = Run(kind="schedule", session_id="seed-builder")
        s = get_schedule(run, team)
        print(f"schedule {team}: {len(s.games) if s else 0} games", flush=True)
    for city in SWEEP_CITIES:
        if recently_swept(city):
            print(f"sweep {city}: already in seed", flush=True)
            continue
        run = Run(kind="city_sweep", session_id="seed-builder")
        out = city_sweep(run, city)
        t = run.totals()["total"]
        print(f"sweep {city}: {out['teams']} teams, ${t['cost']:.3f}", flush=True)
    rows = db.query("SELECT key, kind, payload FROM cache WHERE kind IN ('spots', 'schedule', 'route', 'reputation', 'sweep')")
    entries = [{"key": r["key"], "kind": r["kind"], "payload": json.loads(r["payload"])} for r in rows]
    (config.DATA_DIR / "seed_cache.json").write_text(json.dumps(entries, indent=1, ensure_ascii=False))
    geos = db.query("SELECT address, lat, lon, display, ok FROM geocode_cache")
    (config.DATA_DIR / "seed_geocodes.json").write_text(json.dumps(geos, indent=1, ensure_ascii=False))
    print(f"saved {len(entries)} cache entries and {len(geos)} geocodes")


if __name__ == "__main__":
    main()
