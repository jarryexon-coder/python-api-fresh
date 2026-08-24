#!/usr/bin/env python3
"""Settle forward WNBA market observations from finalized box scores."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode


def main() -> int:
    parser = argparse.ArgumentParser(description="Attach WNBA final player results to forward market snapshots.")
    parser.add_argument("--date", required=True, help="Completed game date (YYYY-MM-DD).")
    args = parser.parse_args()
    secret = os.getenv("PREDICTION_IMPORT_SECRET")
    if not secret:
        print(json.dumps({"success": False, "error": "PREDICTION_IMPORT_SECRET is not configured."}))
        return 2
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from app import app as flask_app
    from api.prediction_ledger import grade_wnba_market_consensus
    with flask_app.test_request_context(
        "/api/prediction-ledger/snapshots/wnba/grade-market-consensus?" + urlencode({"date": args.date}),
        method="POST",
        headers={"X-Prediction-Import-Key": secret},
    ):
        response = grade_wnba_market_consensus()
    if isinstance(response, tuple):
        response, status = response
    else:
        status = response.status_code
    payload = response.get_json() or {"success": False, "error": "No JSON response returned."}
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if status < 400 and payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
