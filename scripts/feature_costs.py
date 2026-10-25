"""Summarize measured costs of the newer features into docs/feature_costs.json for the report.

Reads the usage logs written while building the seed (runtime/seed_build.db) and the app database
(runtime/home_turf.db, for Reputation runs). Run after build_seed_cache.py and take_screenshots.py.
"""

from __future__ import annotations

import json
import sqlite3
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def runs(db_path: Path, where: str) -> list[dict]:
    if not db_path.exists():
        return []
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    q = (f"SELECT run_id, SUM(input_tokens) input, SUM(output_tokens) output, SUM(cached_tokens) cached, SUM(web_searches) web_searches, "
         f"SUM(cost_usd) cost, SUM(latency_ms)/1000.0 seconds FROM usage WHERE {where} GROUP BY run_id")
    return [dict(r) for r in con.execute(q).fetchall()]


def avg(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    return {k: st.mean(r[k] or 0 for r in rows) for k in ("input", "output", "cached", "web_searches", "cost", "seconds")} | {"runs": len(rows)}


def main() -> None:
    import config

    seed_db = config.RUNTIME_DIR / "seed_build.db"
    app_db = config.RUNTIME_DIR / "home_turf.db"
    out: dict = {}
    out["sweep"] = avg(runs(seed_db, "run_kind = 'city_sweep'"))
    out["wide"] = avg(runs(seed_db, "run_id IN (SELECT run_id FROM usage WHERE agent = 'scout_wide')"))
    out["reputation"] = avg(runs(app_db, "run_kind = 'reputation' AND web_searches >= 0 AND agent = 'reputation'"))
    config.DB_PATH = seed_db
    from core.citymap import known_points

    pts = known_points()
    teams = {t["team"] for p in pts for t in p["teams"]}
    cities = {p["city"].split(",")[0] for p in pts}
    sweeps = sqlite3.connect(seed_db).execute("SELECT payload FROM cache WHERE kind = 'sweep'").fetchall()
    out["sweep_teams"] = round(st.mean(json.loads(p[0])["teams"] for p in sweeps)) if sweeps else 0
    out["sweep_cost"] = out["sweep"]["cost"] if out["sweep"] else 0
    out["teams_mapped"], out["cities"] = len(teams), len(cities)
    (ROOT / "docs" / "feature_costs.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
