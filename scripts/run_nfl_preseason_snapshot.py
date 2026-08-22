#!/usr/bin/env python3
"""Store the current NFL preseason research snapshot outside the web worker."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode


def main() -> int:
    parser = argparse.ArgumentParser(description="Store NFL preseason player-projection and game-market snapshots.")
    parser.add_argument("--max-events", type=int, default=20, choices=range(1, 21), metavar="1..20")
    args = parser.parse_args()
    secret = os.getenv("PREDICTION_IMPORT_SECRET")
    if not secret:
        print(json.dumps({"success": False, "error": "PREDICTION_IMPORT_SECRET is not configured."}))
        return 2
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from app import app as flask_app
    from api.prediction_ledger import snapshot_nfl_preseason
    with flask_app.test_request_context(
        "/api/prediction-ledger/snapshots/nfl/preseason?" + urlencode({"max_events": str(args.max_events)}),
        method="POST", headers={"X-Prediction-Import-Key": secret},
    ):
        response = snapshot_nfl_preseason()
    if isinstance(response, tuple):
        response, status = response
    else:
        status = response.status_code
    payload = response.get_json() or {"success": False, "error": "No JSON response returned."}
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if status < 400 and payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
