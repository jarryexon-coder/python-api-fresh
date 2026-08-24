#!/usr/bin/env python3
"""Store isolated WNBA multi-book player-prop observations before games."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode


def main() -> int:
    parser = argparse.ArgumentParser(description="Store WNBA multi-book pregame market observations.")
    parser.add_argument("--markets", default="player_points,player_rebounds,player_assists,player_threes,player_points_rebounds_assists", help="Comma-separated supported The Odds API WNBA market keys.")
    parser.add_argument("--max-events", type=int, default=6, choices=range(1, 13), metavar="1..12")
    args = parser.parse_args()
    secret = os.getenv("PREDICTION_IMPORT_SECRET")
    if not secret:
        print(json.dumps({"success": False, "error": "PREDICTION_IMPORT_SECRET is not configured."}))
        return 2
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from app import app as flask_app
    from api.prediction_ledger import snapshot_wnba_market_consensus
    query = urlencode({"markets": args.markets, "max_events": str(args.max_events)})
    with flask_app.test_request_context(
        "/api/prediction-ledger/snapshots/wnba/market-consensus?" + query,
        method="POST",
        headers={"X-Prediction-Import-Key": secret},
    ):
        response = snapshot_wnba_market_consensus()
    if isinstance(response, tuple):
        response, status = response
    else:
        status = response.status_code
    payload = response.get_json() or {"success": False, "error": "No JSON response returned."}
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if status < 400 and payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
