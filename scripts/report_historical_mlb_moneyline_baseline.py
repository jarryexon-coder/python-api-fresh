#!/usr/bin/env python3
"""Report the isolated historical MLB pregame moneyline market baseline."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    secret = os.getenv("PREDICTION_IMPORT_SECRET")
    if not secret:
        print(json.dumps({"success": False, "error": "PREDICTION_IMPORT_SECRET is not configured."}))
        return 2

    repository_root = str(Path(__file__).resolve().parents[1])
    if repository_root not in sys.path:
        sys.path.insert(0, repository_root)

    from app import app as flask_app
    from api.prediction_ledger import report_historical_mlb_moneyline_baseline

    with flask_app.test_request_context(
        "/api/prediction-ledger/backtest/mlb/moneyline-baseline/report",
        method="GET",
        headers={"X-Prediction-Import-Key": secret},
    ):
        response = report_historical_mlb_moneyline_baseline()
    if isinstance(response, tuple):
        response, status = response
    else:
        status = response.status_code
    payload = response.get_json() or {"success": False, "error": "No JSON response returned."}
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if status < 400 and payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
