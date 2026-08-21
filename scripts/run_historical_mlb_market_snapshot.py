#!/usr/bin/env python3
"""Backfill verified MLB multi-book pregame consensus snapshots for research."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode


def main() -> int:
    parser = argparse.ArgumentParser(description="Store historical MLB multi-book market consensus records.")
    parser.add_argument("--date", required=True, help="Completed game date (YYYY-MM-DD).")
    parser.add_argument("--snapshot", help="Pregame historical odds snapshot in ISO-8601 UTC.")
    parser.add_argument("--markets", default="batter_hits", help="Comma-separated The Odds API market keys.")
    parser.add_argument("--max-events", type=int, default=3, choices=range(1, 4), metavar="1..3")
    args = parser.parse_args()
    secret = os.getenv("PREDICTION_IMPORT_SECRET")
    if not secret:
        print(json.dumps({"success": False, "error": "PREDICTION_IMPORT_SECRET is not configured."}))
        return 2
    repository_root = str(Path(__file__).resolve().parents[1])
    if repository_root not in sys.path:
        sys.path.insert(0, repository_root)
    from app import app as flask_app
    from api.prediction_ledger import snapshot_historical_mlb_market_consensus

    query = urlencode({"date": args.date, "snapshot": args.snapshot or f"{args.date}T13:00:00Z", "markets": args.markets, "max_events": str(args.max_events)})
    with flask_app.test_request_context(
        "/api/prediction-ledger/snapshots/mlb/historical-market-consensus?" + query,
        method="POST",
        headers={"X-Prediction-Import-Key": secret},
    ):
        response = snapshot_historical_mlb_market_consensus()
    if isinstance(response, tuple):
        response, status = response
    else:
        status = response.status_code
    payload = response.get_json() or {"success": False, "error": "No JSON response returned."}
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if status < 400 and payload.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
