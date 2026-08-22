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
            requested = str(row.get("game_date") or "")
            commence = str(row.get("commence_time") or "")[:10]
            try:
                allowed = {datetime.fromisoformat(requested).date().isoformat(), (datetime.fromisoformat(requested).date() + timedelta(days=1)).isoformat()}
            except ValueError:
                allowed = set()
            if commence and commence not in allowed:
                snapshot.reference.set({"excluded_from_evaluation": True, "exclusion_reason": "Historical snapshot predates scheduled event; not a same-game pregame observation."}, merge=True)
                excluded += 1
            else:
                retained += 1
    print(json.dumps({"success": True, "read_only": False, "recoverable": True, "excluded": excluded, "retained": retained, "message": "Invalid future-schedule observations were marked excluded, not deleted."}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
