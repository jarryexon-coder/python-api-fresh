#!/usr/bin/env python3
"""Persist an auditable MLB pregame context snapshot outside web-worker limits."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode


def main() -> int:
    parser = argparse.ArgumentParser(description="Store current MLB lineup, pitcher, venue, and weather context.")
    parser.add_argument("--date", help="Optional UTC game date filter (YYYY-MM-DD).")
    parser.add_argument("--max-events", type=int, default=15, choices=range(1, 16), metavar="1..15")
    args = parser.parse_args()
    secret = os.getenv("PREDICTION_IMPORT_SECRET")
    if not secret:
        print(json.dumps({"success": False, "error": "PREDICTION_IMPORT_SECRET is not configured."}))
        return 2
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from app import app as flask_app
    from api.prediction_ledger import snapshot_mlb_pregame_context
    query = urlencode({key: value for key, value in {"date": args.date, "max_events": str(args.max_events)}.items() if value})
    with flask_app.test_request_context(
        "/api/prediction-ledger/snapshots/mlb/pregame-context?" + query,
        method="POST",
        headers={"X-Prediction-Import-Key": secret},
    ):
        response = snapshot_mlb_pregame_context()
    if isinstance(response, tuple):
        response, status = response
    else:
        status = response.status_code
    payload = response.get_json() or {"success": False, "error": "No JSON response returned."}
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if status < 400 and payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
