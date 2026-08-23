#!/usr/bin/env python3
"""Preview or import isolated historical MLB pregame moneyline baselines."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode


def main() -> int:
    parser = argparse.ArgumentParser(description="Import historical MLB moneylines with verified final winners.")
    parser.add_argument("--date", required=True, help="Historical snapshot date (YYYY-MM-DD).")
    parser.add_argument("--snapshot", required=True, help="Pregame snapshot timestamp (YYYY-MM-DDTHH:MM:SSZ).")
    parser.add_argument("--max-events", type=int, default=3, choices=range(1, 4), metavar="1..3")
    parser.add_argument("--commit", action="store_true", help="Write records after reviewing preview output.")
    args = parser.parse_args()
    secret = os.getenv("PREDICTION_IMPORT_SECRET")
    if not secret:
        print(json.dumps({"success": False, "error": "PREDICTION_IMPORT_SECRET is not configured."}))
        return 2
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from app import app as flask_app
    from api.prediction_ledger import backfill_historical_mlb_moneyline_baseline
    query = urlencode({"date": args.date, "snapshot": args.snapshot, "max_events": str(args.max_events), "commit": "true" if args.commit else "false"})
    with flask_app.test_request_context(
        "/api/prediction-ledger/backtest/mlb/moneyline-baseline?" + query,
        method="POST",
        headers={"X-Prediction-Import-Key": secret},
    ):
        response = backfill_historical_mlb_moneyline_baseline()
    if isinstance(response, tuple):
        response, status = response
    else:
        status = response.status_code
    payload = response.get_json() or {"success": False, "error": "No JSON response returned."}
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if status < 400 and payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
