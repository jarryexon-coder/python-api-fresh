#!/usr/bin/env python3
"""Chronologically test a conservative MLB market-probability calibration.

The script is research-only.  It never changes app predictions, model
profiles, or historical observations.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


PRIOR_STRENGTH = 40.0
MIN_TRAINING_SAMPLES = 400
MIN_HOLDOUT_SAMPLES = 100
MIN_BRIER_IMPROVEMENT = 0.003


def probability_band(probability: float) -> str:
    lower = int(probability // 10) * 10
    return f"{lower}-{lower + 9}%"


def brier(items: list[tuple[float, int]]) -> float | None:
    return round(sum((probability - outcome) ** 2 for probability, outcome in items) / len(items), 4) if items else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a chronological MLB market-probability calibration.")
    parser.add_argument("--training-end", required=True, help="Last date included in training (YYYY-MM-DD).")
    args = parser.parse_args()
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)

    from app import app as flask_app
    from firebase_admin import firestore

    with flask_app.app_context():
        store = firestore.client()
        raw_rows = [snapshot.to_dict() or {} for snapshot in store.collection("prediction_market_snapshots").where("record_type", "==", "historical_pregame_market_consensus").stream()]

    rows = []
    for row in raw_rows:
        if row.get("consensus_method") != "median_devig_per_book_v2":
            continue
        probability = row.get("fair_probability_over")
        actual, line = row.get("actual_value"), row.get("line")
        date = str(row.get("game_date") or "")
        if not isinstance(probability, (int, float)) or not isinstance(actual, (int, float)) or not isinstance(line, (int, float)) or not date or actual == line:
            continue
        rows.append({"date": date, "market": str(row.get("market") or "Other"), "probability": float(probability) / 100, "outcome": int(actual > line)})

    training = [row for row in rows if row["date"] <= args.training_end]
    holdout = [row for row in rows if row["date"] > args.training_end]
    profiles: dict[str, dict] = {}
    by_market_train: dict[str, list[dict]] = defaultdict(list)
    for row in training:
        by_market_train[row["market"]].append(row)
    for market, items in by_market_train.items():
        market_rate = sum(item["outcome"] for item in items) / len(items)
        bands: dict[str, list[dict]] = defaultdict(list)
        for item in items:
            bands[probability_band(item["probability"] * 100)].append(item)
        profiles[market] = {
            "market_rate": market_rate,
            "samples": len(items),
            "bands": {
                band: {"samples": len(values), "over_rate": sum(value["outcome"] for value in values) / len(values)}
                for band, values in bands.items()
            },
        }

    by_market_holdout: dict[str, list[dict]] = defaultdict(list)
    for row in holdout:
        by_market_holdout[row["market"]].append(row)

    results = {}
    for market in sorted(set(profiles) | set(by_market_holdout)):
        profile = profiles.get(market)
        evaluation = by_market_holdout.get(market, [])
        raw_pairs = [(row["probability"], row["outcome"]) for row in evaluation]
        calibrated_pairs = []
        if profile:
            for row in evaluation:
                band = profile["bands"].get(probability_band(row["probability"] * 100))
                if band:
                    # Beta-style shrinkage prevents a thin band from claiming a false edge.
                    calibrated = (band["over_rate"] * band["samples"] + profile["market_rate"] * PRIOR_STRENGTH) / (band["samples"] + PRIOR_STRENGTH)
                else:
                    calibrated = profile["market_rate"]
                calibrated_pairs.append((calibrated, row["outcome"]))
        raw_brier = brier(raw_pairs)
        calibrated_brier = brier(calibrated_pairs)
        train_count = int(profile["samples"]) if profile else 0
        holdout_count = len(evaluation)
        improvement = round(raw_brier - calibrated_brier, 4) if raw_brier is not None and calibrated_brier is not None else None
        results[market] = {
            "training_samples": train_count,
            "holdout_samples": holdout_count,
            "raw_market_brier": raw_brier,
            "calibrated_market_brier": calibrated_brier,
            "brier_improvement": improvement,
            "eligible_for_future_manual_review": bool(train_count >= MIN_TRAINING_SAMPLES and holdout_count >= MIN_HOLDOUT_SAMPLES and improvement is not None and improvement >= MIN_BRIER_IMPROVEMENT),
            "reason": "Requires at least a 0.003 lower chronological-holdout Brier score and minimum sample sizes; it is not a bet-selection signal.",
        }

    print(json.dumps({
        "success": True,
        "isolated": True,
        "training_end": args.training_end,
        "training_dates": sorted({row["date"] for row in training}),
        "holdout_dates": sorted({row["date"] for row in holdout}),
        "minimums": {"training_samples": MIN_TRAINING_SAMPLES, "holdout_samples": MIN_HOLDOUT_SAMPLES, "brier_improvement": MIN_BRIER_IMPROVEMENT},
        "markets": results,
        "message": "Chronological calibration evaluation only. It does not make wagers, generate picks, or change any live app output.",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
