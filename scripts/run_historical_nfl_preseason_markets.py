#!/usr/bin/env python3
"""Preview or persist isolated historical NFL preseason game-market snapshots."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode


def main() -> int:
    parser = argparse.ArgumentParser(description="Import historical NFL preseason featured markets for research.")
    parser.add_argument("--date", required=True, help="Completed game date, YYYY-MM-DD.")
    parser.add_argument("--snapshot", help="Pregame timestamp in UTC; defaults to 13:00 UTC on --date.")
    parser.add_argument("--max-events", type=int, default=3, choices=range(1, 4), metavar="1..3")
    parser.add_argument("--offset", type=int, default=0, help="Zero-based eligible-event offset for additional same-snapshot batches.")
    parser.add_argument("--commit", action="store_true", help="Write records after reviewing the default preview.")
    args = parser.parse_args()
    secret = os.getenv("PREDICTION_IMPORT_SECRET")
    if not secret:
        print(json.dumps({"success": False, "error": "PREDICTION_IMPORT_SECRET is not configured."}))
        return 2
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from app import app as flask_app
    from api.prediction_ledger import snapshot_historical_nfl_preseason_markets
    query = urlencode({"date": args.date, "snapshot": args.snapshot or f"{args.date}T13:00:00Z", "max_events": str(args.max_events), "offset": str(max(0, args.offset)), "commit": "true" if args.commit else "false"})
    with flask_app.test_request_context(
        "/api/prediction-ledger/snapshots/nfl/preseason/historical-markets?" + query,
        method="POST", headers={"X-Prediction-Import-Key": secret},
    ):
        response = snapshot_historical_nfl_preseason_markets()
    if isinstance(response, tuple):
        response, status = response
    else:
        status = response.status_code
    payload = response.get_json() or {"success": False, "error": "No JSON response returned."}
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if status < 400 and payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
