#!/usr/bin/env python3
"""List NFL preseason market records without a verified final score."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from app import app as flask_app
    from firebase_admin import firestore

    with flask_app.app_context():
        store = firestore.client()
        rows = [snapshot.to_dict() or {} for snapshot in store.collection("prediction_nfl_preseason_snapshots").where("record_type", "==", "historical_pregame_game_market_snapshot").stream()]
    unverified = [row for row in rows if not isinstance(row.get("final_score"), dict)]
    samples = [{
        "date": row.get("game_date"), "snapshot": row.get("snapshot"), "commence_time": row.get("commence_time"),
        "event_id": row.get("event_id"), "game": row.get("game"), "book_count": row.get("book_count"),
    } for row in sorted(unverified, key=lambda item: (str(item.get("game_date") or ""), str(item.get("commence_time") or "")))[:40]]
    print(json.dumps({
        "success": True,
        "read_only": True,
        "isolated": True,
        "records_found": len(rows),
        "verified_final_scores": len(rows) - len(unverified),
        "unverified_final_scores": len(unverified),
        "samples": samples,
        "message": "Audit only. It does not change historical records, final scores, or any model.",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
