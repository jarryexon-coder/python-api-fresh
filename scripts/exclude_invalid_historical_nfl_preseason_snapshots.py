#!/usr/bin/env python3
"""Safely exclude NFL records captured before their game date from evaluation.

The original documents are retained for auditability. This script merely marks
the known-invalid observations so they cannot affect any report or model.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


def main() -> int:
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from app import app as flask_app
    from firebase_admin import firestore

    with flask_app.app_context():
        store = firestore.client()
        snapshots = list(store.collection("prediction_nfl_preseason_snapshots").where("record_type", "==", "historical_pregame_game_market_snapshot").stream())
        excluded = retained = 0
        for snapshot in snapshots:
            row = snapshot.to_dict() or {}
            snapshot_time = str(row.get("snapshot") or "")
            commence_time = str(row.get("commence_time") or "")
            try:
                captured = datetime.fromisoformat(snapshot_time.replace("Z", "+00:00"))
                commence = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
                valid = 0 <= (commence - captured).total_seconds() / 3600 <= 16
            except ValueError:
                valid = False
            if not valid:
                snapshot.reference.set({"excluded_from_evaluation": True, "exclusion_reason": "Historical snapshot was more than 16 hours before event start; not a same-game pregame observation."}, merge=True)
                excluded += 1
            else:
                snapshot.reference.set({"excluded_from_evaluation": False, "exclusion_reason": None}, merge=True)
                retained += 1
    print(json.dumps({"success": True, "read_only": False, "recoverable": True, "excluded": excluded, "retained": retained, "message": "Invalid future-schedule observations were marked excluded, not deleted."}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
