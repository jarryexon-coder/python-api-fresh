#!/usr/bin/env python3
"""Report settled, forward-captured MLB market snapshots separately from backtests.

This is a data-quality and market-baseline report.  It does not generate a
model, select wagers, change thresholds, or modify live app output.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def american_profit(price: float, won: bool) -> float:
    if not won:
        return -1.0
    return price / 100 if price > 0 else 100 / abs(price)


def probability_band(probability: float) -> str:
    lower = int(probability // 10) * 10
    return f"{lower}-{lower + 9}%"


def main() -> int:
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from app import app as flask_app
    from firebase_admin import firestore

    with flask_app.app_context():
        store = firestore.client()
        raw_rows = [snapshot.to_dict() or {} for snapshot in store.collection("prediction_market_snapshots").where("record_type", "==", "pregame_market_consensus").stream()]

    usable = []
    for row in raw_rows:
        if row.get("consensus_method") != "median_devig_per_book_v2" or not row.get("settled_at"):
            continue
        line, actual = row.get("line"), row.get("actual_value")
        fair, over, under = row.get("fair_probability_over"), row.get("over_odds"), row.get("under_odds")
        if not all(isinstance(value, (int, float)) for value in (line, actual, fair, over, under)) or actual == line:
            continue
        usable.append(row)

    def metrics(rows: list[dict]) -> dict:
        total = len(rows)
        if not total:
            return {"samples": 0, "actual_over_rate": None, "average_fair_over_probability": None, "brier_score": None, "blind_over_roi_percent": None, "blind_under_roi_percent": None}
        over_wins = sum(float(row["actual_value"]) > float(row["line"]) for row in rows)
        brier = sum(((float(row["fair_probability_over"]) / 100) - int(float(row["actual_value"]) > float(row["line"]))) ** 2 for row in rows) / total
        over_units = sum(american_profit(float(row["over_odds"]), float(row["actual_value"]) > float(row["line"])) for row in rows)
        under_units = sum(american_profit(float(row["under_odds"]), float(row["actual_value"]) < float(row["line"])) for row in rows)
        return {
            "samples": total,
            "actual_over_rate": round(over_wins / total * 100, 1),
            "average_fair_over_probability": round(sum(float(row["fair_probability_over"]) for row in rows) / total, 1),
            "brier_score": round(brier, 4),
            "blind_over_roi_percent": round(over_units / total * 100, 2),
            "blind_under_roi_percent": round(under_units / total * 100, 2),
        }

    by_date: dict[str, list[dict]] = defaultdict(list)
    by_market: dict[str, list[dict]] = defaultdict(list)
    by_band: dict[str, list[dict]] = defaultdict(list)
    for row in usable:
        by_date[str(row.get("game_date") or "unknown")].append(row)
        by_market[str(row.get("market") or "Other")].append(row)
        by_band[probability_band(float(row["fair_probability_over"]))].append(row)
    dates = sorted(date for date in by_date if date != "unknown")
    books = [float(row.get("book_count") or 0) for row in usable]
    print(json.dumps({
        "success": True,
        "isolated": True,
        "record_type": "pregame_market_consensus",
        "scope": "forward_captured_only",
        "date_range": {"first": dates[0] if dates else None, "last": dates[-1] if dates else None, "days": len(dates)},
        "settled_two_sided_records": len(usable),
        "average_book_count": round(sum(books) / len(books), 2) if books else None,
        "overall": metrics(usable),
        "by_date": {date: metrics(rows) for date, rows in sorted(by_date.items())},
        "by_market": {market: metrics(rows) for market, rows in sorted(by_market.items())},
        "calibration_by_fair_probability_band": {band: metrics(rows) for band, rows in sorted(by_band.items())},
        "message": "Forward-captured market observations only. Blind-side ROI audits pricing quality; it is not a recommendation or a live model.",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
