"""Build data/team_logos.json: team name -> logo URL, colors, league (from ESPN's public team lists).

Run once:  python scripts/build_team_logos.py   (no API key needed). Logos are linked, not copied.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
LEAGUES = {
    "NFL": "football/nfl",
    "college": "football/college-football",
    "NBA": "basketball/nba",
    "MLB": "baseball/mlb",
    "NHL": "hockey/nhl",
    "MLS": "soccer/usa.1",
    "WNBA": "basketball/wnba",
    "EPL": "soccer/eng.1",
    "EFL": "soccer/eng.2",
    "LaLiga": "soccer/esp.1",
    "Bundesliga": "soccer/ger.1",
    "SerieA": "soccer/ita.1",
    "Ligue1": "soccer/fra.1",
    "SPFL": "soccer/sco.1",
    "LigaMX": "soccer/mex.1",
}


def main() -> None:
    teams = []
    for league, path in LEAGUES.items():
        url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/teams?limit=1000"
        data = httpx.get(url, timeout=30).json()
        for item in data["sports"][0]["leagues"][0]["teams"]:
            t = item["team"]
            logos = t.get("logos") or []
            if not logos:
                continue
            teams.append({
                "name": t.get("displayName", ""),
                "short": t.get("shortDisplayName", ""),
                "nickname": t.get("nickname", ""),
                "location": t.get("location", ""),
                "abbr": t.get("abbreviation", ""),
                "league": league,
                "color": "#" + (t.get("color") or "0f2240"),
                "alt_color": "#" + (t.get("alternateColor") or "b8902f"),
                "logo": logos[0]["href"],
            })
        print(league, sum(1 for t in teams if t["league"] == league))
    (ROOT / "data" / "team_logos.json").write_text(json.dumps(teams, indent=0, ensure_ascii=False))
    print("saved", len(teams))


if __name__ == "__main__":
    main()
