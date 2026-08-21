#!/usr/bin/env python3
"""Report the quality of verified historical MLB multi-book consensus data.

This is an observational report, not a prediction model or a betting strategy.
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
    repository_root = str(Path(__file__).resolve().parents[1])
    if repository_root not in sys.path:
        sys.path.insert(0, repository_root)

    from app import app as flask_app  # Initializes the production Firestore client under railway run.
    from firebase_admin import firestore

    with flask_app.app_context():
        store = firestore.client()
        rows = [snapshot.to_dict() or {} for snapshot in store.collection("prediction_market_snapshots").where("record_type", "==", "historical_pregame_market_consensus").stream()]

    usable = []
    for row in rows:
        line = row.get("line")
        actual = row.get("actual_value")
        fair = row.get("fair_probability_over")
        over = row.get("over_odds")
        under = row.get("under_odds")
        if not all(isinstance(value, (int, float)) for value in (line, actual, fair, over, under)):
            continue
        if actual == line:  # A push is not an Over/Under probability outcome.
            continue
        usable.append(row)

    dates = sorted({str(row.get("game_date") or "") for row in usable if row.get("game_date")})
    calibration: dict[str, list[dict]] = defaultdict(list)
    for row in usable:
        calibration[probability_band(float(row["fair_probability_over"]))].append(row)

    def metrics(items: list[dict]) -> dict:
        total = len(items)
        over_wins = sum(float(row["actual_value"]) > float(row["line"]) for row in items)
        brier = sum(((float(row["fair_probability_over"]) / 100) - (1 if float(row["actual_value"]) > float(row["line"]) else 0)) ** 2 for row in items) / total if total else None
        over_units = sum(american_profit(float(row["over_odds"]), float(row["actual_value"]) > float(row["line"])) for row in items)
        under_units = sum(american_profit(float(row["under_odds"]), float(row["actual_value"]) < float(row["line"])) for row in items)
        return {
            "samples": total,
            "actual_over_rate": round(over_wins / total * 100, 1) if total else None,
            "average_fair_over_probability": round(sum(float(row["fair_probability_over"]) for row in items) / total, 1) if total else None,
            "brier_score": round(brier, 4) if brier is not None else None,
            "blind_over_roi_percent": round(over_units / total * 100, 2) if total else None,
            "blind_under_roi_percent": round(under_units / total * 100, 2) if total else None,
        }

    books = [float(row.get("book_count") or 0) for row in usable]
    report = {
        "success": True,
        "isolated": True,
        "record_type": "historical_pregame_market_consensus",
        "date_range": {"first": dates[0] if dates else None, "last": dates[-1] if dates else None, "days": len(dates)},
        "records_found": len(rows),
        "settled_two_sided_records": len(usable),
        "average_book_count": round(sum(books) / len(books), 2) if books else None,
        "overall": metrics(usable),
        "calibration_by_fair_probability_band": {band: metrics(items) for band, items in sorted(calibration.items())},
        "message": "Data-quality report only. Blind-side ROI is shown to audit the market baseline, not as a recommendation or a live model.",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
