#!/usr/bin/env python3
"""Preview or remove a precisely targeted isolated MLB backtest batch."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove a bad historical MLB backtest batch.")
    parser.add_argument("--game-date", required=True, help="Stored game_date for the invalid batch.")
    parser.add_argument("--snapshot", required=True, help="Stored snapshot for the invalid batch.")
    parser.add_argument("--commit", action="store_true", help="Actually delete the matched records. Default is preview only.")
    args = parser.parse_args()

    repository_root = str(Path(__file__).resolve().parents[1])
    if repository_root not in sys.path:
        sys.path.insert(0, repository_root)
    from app import db

    if not db:
        print(json.dumps({"success": False, "error": "Firestore is unavailable."}))
        return 2

    rows = [
        snapshot
        for snapshot in db.collection("prediction_backtest_ledger").where("sport", "==", "mlb").stream()
        if (snapshot.to_dict() or {}).get("isolation") == "historical_backtest"
        and (snapshot.to_dict() or {}).get("game_date") == args.game_date
        and (snapshot.to_dict() or {}).get("snapshot") == args.snapshot
    ]
    if args.commit:
        batch = db.batch()
        for snapshot in rows:
            batch.delete(snapshot.reference)
        if rows:
            batch.commit()
    print(json.dumps({
        "success": True,
        "preview": not args.commit,
        "game_date": args.game_date,
        "snapshot": args.snapshot,
        "matched": len(rows),
        "deleted": len(rows) if args.commit else 0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
