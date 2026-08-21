#!/usr/bin/env python3
"""Run an isolated MLB historical backtest outside the web-worker timeout.

Use through ``railway run`` so the script receives the same production
provider keys and Firestore service account as the API.  It intentionally
calls the existing protected route handler in a Flask request context: this
keeps the record schema and validation identical to the preview endpoint
without holding an HTTP request open for several historical events.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode


def main() -> int:
    parser = argparse.ArgumentParser(description="Create isolated MLB historical backtest records.")
    parser.add_argument("--date", required=True, help="Completed game date (YYYY-MM-DD).")
    parser.add_argument("--snapshot", help="Pregame historical odds snapshot in ISO-8601 UTC.")
    parser.add_argument("--markets", default="batter_hits", help="Comma-separated The Odds API market keys.")
    parser.add_argument("--model", choices=("v1", "v2", "v2.1", "v2.2", "v2.3", "v2.4"), default="v1", help="Historical model version to import.")
    parser.add_argument("--max-events", type=int, default=1, choices=range(1, 4), metavar="1..3")
    parser.add_argument("--preview", action="store_true", help="List events and estimated credits without writing records.")
    args = parser.parse_args()

    secret = os.getenv("PREDICTION_IMPORT_SECRET")
    if not secret:
        print(json.dumps({"success": False, "error": "PREDICTION_IMPORT_SECRET is not configured."}))
        return 2

    # Executing a file from scripts/ does not automatically put the repository
    # root on Python's import path.
    repository_root = str(Path(__file__).resolve().parents[1])
    if repository_root not in sys.path:
        sys.path.insert(0, repository_root)

    # Importing app initializes the production Firestore client, exactly as
    # Railway does for the API service.  Delay it until after --help parsing.
    from app import app as flask_app
    from api.prediction_ledger import historical_mlb_backtest

    query = {
        "date": args.date,
        "snapshot": args.snapshot or f"{args.date}T15:00:00Z",
        "markets": args.markets,
        "model": args.model,
        "max_events": str(args.max_events),
        "commit": "false" if args.preview else "true",
    }
    with flask_app.test_request_context(
        "/api/prediction-ledger/backtest/mlb?" + urlencode(query),
        method="POST",
        headers={"X-Prediction-Import-Key": secret},
    ):
        response = historical_mlb_backtest()

    if isinstance(response, tuple):
        response, status = response
    else:
        status = response.status_code
    payload = response.get_json() or {"success": False, "error": "No JSON response returned."}
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if status < 400 and payload.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
