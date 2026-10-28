"""Load real data for one city: every NFL team's fan bar, the bars' public reputation (photos and
review themes), and team schedules. Writes into the seed-building database; then run
build_seed_cache.py to export. Usage: python scripts/build_real_city.py "Boston, MA" "New England Patriots"
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402

config.DB_PATH = config.RUNTIME_DIR / "seed_build.db"

from agents.reputation import reputation  # noqa: E402
from agents.schedule import get_schedule  # noqa: E402
from core import db  # noqa: E402
from core.budget import Run  # noqa: E402
from core.orchestrator import find_watch_spots  # noqa: E402
from ui.team_logos import _teams  # noqa: E402


def main(city: str, home_team: str) -> None:
    db.init_db()
    short = city.split(",")[0]
    nfl = sorted(t["name"] for t in _teams() if t["league"] == "NFL" and t["name"] != home_team)

    def one(team: str) -> str:
        r = find_watch_spots(f"{team} fans in {short}", session_id="real-city")
        spots = [s["bar_name"] for g in r.get("groups", []) for s in g["spots"] if s["status"] in ("confirmed", "likely")]
        cost = r["run"].totals()["total"]["cost"]
        return f"{team}: {', '.join(spots[:2]) or 'none found'} (${cost:.3f})"

    with ThreadPoolExecutor(max_workers=4) as pool:
        for line in pool.map(one, nfl):
            print(line, flush=True)

    # Photos + review themes for the real bars we now know in this city (cached 30 days).
    bars = db.query("SELECT * FROM bars WHERE is_demo = 0 AND city LIKE ?", (f"{short}%",))
    def rep(b: dict) -> str:
        try:
            out = reputation(Run(kind="reputation", session_id="real-city"), b)
            return f"  reputation {b['name']}: {len((out or {}).get('photos', []))} photos, {len((out or {}).get('themes', []))} themes"
        except Exception as exc:  # noqa: BLE001
            return f"  reputation {b['name']}: skipped ({type(exc).__name__})"
    with ThreadPoolExecutor(max_workers=4) as pool:
        for line in pool.map(rep, bars):
            print(line, flush=True)
    for team in ("New York Giants", home_team):
        s = get_schedule(Run(kind="schedule", session_id="real-city"), team)
        print(f"schedule {team}: {len(s.games) if s else 0} games", flush=True)
    total = db.one("SELECT COALESCE(SUM(cost_usd),0) c FROM usage WHERE session_id = 'real-city'")["c"]
    print(f"done. total spend ${total:.3f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "Boston, MA", sys.argv[2] if len(sys.argv) > 2 else "New England Patriots")
