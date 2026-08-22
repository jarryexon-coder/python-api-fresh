#!/usr/bin/env python3
"""Read-only availability check for NFL preseason research inputs.

This intentionally does not create predictions, snapshots, or calibration
records.  It confirms the two feeds we can honestly use before building a
separate preseason ledger: Tank01 player projections and The Odds API's
featured NFL preseason game markets.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import requests


RAPID_HOST = "tank01-nfl-live-in-game-real-time-statistics-nfl.p.rapidapi.com"
PRESEASON_SPORT = "americanfootball_nfl_preseason"


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _projection_params() -> dict[str, Any]:
    return {
        "week": os.getenv("TANK01_NFL_PROJECTION_WEEK", "1"),
        "archiveSeason": os.getenv("TANK01_NFL_PROJECTION_SEASON", str(datetime.now().year)),
        "itemFormat": "list",
        "twoPointConversions": 2,
        "passYards": ".04",
        "passAttempts": "-.5",
        "passTD": 4,
        "passCompletions": 1,
        "passInterceptions": -2,
        "pointsPerReception": 1,
        "carries": ".2",
        "rushYards": ".1",
        "rushTD": 6,
        "fumbles": -2,
        "receivingYards": ".1",
        "receivingTD": 6,
        "targets": ".1",
        "fgMade": 3,
        "fgMissed": -1,
        "xpMade": 1,
        "xpMissed": -1,
    }


def _probe_tank01() -> dict[str, Any]:
    key = os.getenv("RAPIDAPI_KEY_TANK01") or os.getenv("RAPIDAPI_KEY")
    if not key:
        return {"available": False, "reason": "RapidAPI key is not configured."}
    try:
        response = requests.get(
            f"https://{RAPID_HOST}/getNFLProjections",
            headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": RAPID_HOST, "Accept": "application/json"},
            params=_projection_params(),
            timeout=30,
        )
        if not response.ok:
            return {"available": False, "status": response.status_code, "reason": "Tank01 did not return projections for the configured week/season."}
        payload = response.json()
        body = payload.get("body", payload) if isinstance(payload, dict) else {}
        raw = body.get("playerProjections", body) if isinstance(body, dict) else []
        rows = list(raw.values()) if isinstance(raw, dict) else raw if isinstance(raw, list) else []
        sample = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("longName"):
                continue
            passing = row.get("Passing") if isinstance(row.get("Passing"), dict) else {}
            rushing = row.get("Rushing") if isinstance(row.get("Rushing"), dict) else {}
            receiving = row.get("Receiving") if isinstance(row.get("Receiving"), dict) else {}
            sample.append({
                "player": row.get("longName"),
                "pass_yards": _number(passing.get("passYds")),
                "rush_yards": _number(rushing.get("rushYds")),
                "receiving_yards": _number(receiving.get("recYds")),
            })
            if len(sample) == 3:
                break
        return {"available": bool(rows), "configured_week": _projection_params()["week"], "configured_season": _projection_params()["archiveSeason"], "player_count": len(rows), "sample": sample}
    except requests.RequestException:
        return {"available": False, "reason": "Tank01 request failed."}


def _probe_preseason_markets() -> dict[str, Any]:
    key = os.getenv("THE_ODDS_API_KEY") or os.getenv("ODDS_API_KEY") or os.getenv("THEODDS_API_KEY")
    if not key:
        return {"available": False, "reason": "The Odds API key is not configured."}
    try:
        response = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{PRESEASON_SPORT}/odds",
            params={"apiKey": key, "regions": "us", "markets": "h2h,spreads,totals", "oddsFormat": "american"},
            timeout=30,
        )
        if not response.ok:
            return {"available": False, "status": response.status_code, "reason": "The Odds API did not return a preseason game-market slate."}
        events = response.json() if isinstance(response.json(), list) else []
        sample = [{"game": f"{item.get('away_team')} @ {item.get('home_team')}", "commence_time": item.get("commence_time"), "book_count": len(item.get("bookmakers") or [])} for item in events[:3] if isinstance(item, dict)]
        return {"available": bool(events), "event_count": len(events), "markets": ["h2h", "spreads", "totals"], "sample": sample}
    except requests.RequestException:
        return {"available": False, "reason": "The Odds API preseason request failed."}


def main() -> int:
    payload = {
        "success": True,
        "research_only": True,
        "taken_at": datetime.now(timezone.utc).isoformat(),
        "tank01_player_projection_feed": _probe_tank01(),
        "odds_api_preseason_game_markets": _probe_preseason_markets(),
        "next_step": "Build the preseason ledger only if both source checks are available. Keep preseason records isolated from regular-season models.",
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
