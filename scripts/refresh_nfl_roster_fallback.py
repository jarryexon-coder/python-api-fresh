"""Refresh nfl_roster_fallback.json from BallDontLie for offline/API-outage use.

Run locally with BALLDONTLIE_API_KEY set. Do not store the key in this file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parent.parent
URL = "https://api.balldontlie.io/nfl/v1/players/active"


def main() -> None:
    key = os.getenv("BALLDONTLIE_API_KEY")
    if not key:
        raise SystemExit("BALLDONTLIE_API_KEY must be set before refreshing the NFL roster fallback.")
    rows, cursor = [], None
    for _ in range(40):
        params = {"per_page": 100}
        if cursor is not None:
            params["cursor"] = cursor
        response = requests.get(URL, headers={"Authorization": key, "Accept": "application/json"}, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()
        page = payload.get("data", [])
        rows.extend(page)
        cursor = payload.get("meta", {}).get("next_cursor")
        if not cursor or not page:
            break
    target = ROOT / "nfl_roster_fallback.json"
    target.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} active NFL players to {target.name}")


if __name__ == "__main__":
    main()
