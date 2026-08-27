#!/usr/bin/env python3
"""Read-only coverage audit for forward MLB prop captures.

Shows all captured rows, settlement status, and the strict two-book consensus
subset used for Phase 2 calibration.  It never generates picks or modifies
records.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


MARKETS = {
    "batter_hits": "Hits",
    "batter_runs_scored": "Runs Scored",
    "batter_rbis": "RBIs",
    "batter_home_runs": "Home Runs",
    "batter_total_bases": "Total Bases",
    "pitcher_strikeouts": "Strikeouts",
}


def main() -> int:
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from app import app as flask_app
    from firebase_admin import firestore

    with flask_app.app_context():
        store = firestore.client()
        rows = [
            item.to_dict() or {}
            for item in store.collection("prediction_market_snapshots")
            .where("record_type", "==", "pregame_market_consensus")
            .stream()
        ]

    rows = [row for row in rows if row.get("sport") == "mlb"]
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("market_key") or "unknown")].append(row)

    report: dict[str, dict] = {}
    for key, label in MARKETS.items():
        items = grouped.get(key, [])
        consensus = [item for item in items if item.get("consensus_method") == "median_devig_per_book_v2"]
        settled = [item for item in consensus if item.get("settled_at")]
        usable = [
            item for item in settled
            if all(isinstance(item.get(field), (int, float)) for field in ("line", "actual_value", "fair_probability_over", "over_odds", "under_odds"))
            and item.get("actual_value") != item.get("line")
        ]
        books = Counter(int(item.get("book_count") or 0) for item in consensus)
        dates = sorted({str(item.get("game_date") or "") for item in items if item.get("game_date")})
        report[key] = {
            "market": label,
            "captured_rows": len(items),
            "two_book_consensus_rows": len(consensus),
            "settled_rows": len(settled),
            "usable_non_push_rows": len(usable),
            "pending_rows": len(consensus) - len(settled),
            "book_count_distribution": dict(sorted(books.items())),
            "dates_captured": len(dates),
            "first_capture_date": dates[0] if dates else None,
            "last_capture_date": dates[-1] if dates else None,
        }

    print(json.dumps({
        "success": True,
        "isolated": True,
        "scope": "forward_mlb_capture_coverage",
        "markets": report,
        "message": "Coverage audit only. A zero means no eligible two-book consensus was saved; it does not imply a player result was missing.",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
