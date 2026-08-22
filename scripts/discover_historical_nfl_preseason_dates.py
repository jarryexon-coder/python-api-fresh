#!/usr/bin/env python3
"""Find which past dates have same-day NFL preseason events to import."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover eligible NFL preseason historical import dates.")
    parser.add_argument("--start", required=True, help="First date to check, YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="Last date to check, YYYY-MM-DD.")
    args = parser.parse_args()
    key = os.getenv("THE_ODDS_API_KEY") or os.getenv("ODDS_API_KEY") or os.getenv("THEODDS_API_KEY")
    if not key:
        print(json.dumps({"success": False, "error": "THE_ODDS_API_KEY is not configured."}))
        return 2
    try:
        start, end = datetime.fromisoformat(args.start).date(), datetime.fromisoformat(args.end).date()
    except ValueError:
        print(json.dumps({"success": False, "error": "Dates must use YYYY-MM-DD."}))
        return 2
    if end < start or (end - start).days > 45:
        print(json.dumps({"success": False, "error": "Use a range from 0 to 45 days."}))
        return 2
    eligible, checked, errors = [], 0, []
    cursor = start
    while cursor <= end:
        snapshot = f"{cursor.isoformat()}T13:00:00Z"
        try:
            response = requests.get(
                "https://api.the-odds-api.com/v4/historical/sports/americanfootball_nfl_preseason/events",
                params={"apiKey": key, "date": snapshot}, timeout=45,
            )
            response.raise_for_status()
            payload = response.json()
            events = payload.get("data", payload) if isinstance(payload, dict) else []
            captured = datetime.fromisoformat(snapshot.replace("Z", "+00:00"))
            same_day = []
            for item in events:
                if not isinstance(item, dict):
                    continue
                try:
                    commence = datetime.fromisoformat(str(item.get("commence_time") or "").replace("Z", "+00:00"))
                except ValueError:
                    continue
                if 0 <= (commence - captured).total_seconds() / 3600 <= 16:
                    same_day.append(item)
            if same_day:
                eligible.append({
                    "date": cursor.isoformat(), "snapshot": snapshot, "event_count": len(same_day),
                    "events": [{"game": f"{item.get('away_team')} @ {item.get('home_team')}", "commence_time": item.get("commence_time")} for item in same_day[:5]],
                })
        except requests.RequestException as error:
            errors.append({"date": cursor.isoformat(), "status": error.response.status_code if error.response else "request error"})
        checked += 1
        cursor += timedelta(days=1)
    print(json.dumps({
        "success": True, "research_only": True, "checked_dates": checked, "eligible_dates": eligible,
        "message": "These dates have NFL preseason games starting within 16 hours of the 13:00 UTC snapshot. Use them for preview-first historical imports only.", "errors": errors,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
