#!/usr/bin/env python3
"""Show historical MLB consensus rows with implausible fair probabilities.

This is a read-only audit. It never edits Firestore data.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit historical MLB consensus price outliers.")
    parser.add_argument("--below", type=float, default=20.0, help="Include fair Over probabilities at or below this percent.")
    parser.add_argument("--above", type=float, default=80.0, help="Include fair Over probabilities at or above this percent.")
    parser.add_argument("--limit", type=int, default=50, choices=range(1, 101), metavar="1..100")
    args = parser.parse_args()
    repository_root = str(Path(__file__).resolve().parents[1])
    if repository_root not in sys.path:
        sys.path.insert(0, repository_root)

    from app import app as flask_app
    from firebase_admin import firestore

    with flask_app.app_context():
        store = firestore.client()
        rows = [snapshot.to_dict() or {} for snapshot in store.collection("prediction_market_snapshots").where("record_type", "==", "historical_pregame_market_consensus").stream()]

    outliers = []
    for row in rows:
        fair = row.get("fair_probability_over")
        if not isinstance(fair, (int, float)) or args.below < fair < args.above:
            continue
        line, actual = row.get("line"), row.get("actual_value")
        outliers.append({
            "date": row.get("game_date"), "game": row.get("game"), "player": row.get("player"), "market": row.get("market"),
            "line": line, "actual": actual, "actual_over": actual > line if isinstance(actual, (int, float)) and isinstance(line, (int, float)) else None,
            "fair_probability_over": fair, "over_odds": row.get("over_odds"), "under_odds": row.get("under_odds"),
            "book_count": row.get("book_count"), "bookmakers": row.get("bookmakers"), "snapshot": row.get("snapshot"),
        })
    outliers.sort(key=lambda row: (float(row.get("fair_probability_over") or 0), str(row.get("date") or ""), str(row.get("player") or "")))
    report = {
        "success": True,
        "read_only": True,
        "thresholds": {"below_or_equal": args.below, "above_or_equal": args.above},
        "outlier_count": len(outliers),
        "samples": outliers[:args.limit],
        "message": "Review these raw stored prices before excluding or correcting any historical observation.",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
