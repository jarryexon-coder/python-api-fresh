#!/usr/bin/env python3
"""Chronologically evaluate forward-captured MLB market probabilities.

This is Phase 2 research only: it measures whether a calibration fitted before
``--training-end`` improves later, untouched results.  It never writes a model
profile, selects a side, or changes the app.
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
    if not items:
        return None
    return round(sum((probability - outcome) ** 2 for probability, outcome in items) / len(items), 4)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a chronological forward MLB market calibration.")
    parser.add_argument("--training-end", required=True, help="Last game date allowed in calibration training (YYYY-MM-DD).")
    args = parser.parse_args()

    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from app import app as flask_app
    from firebase_admin import firestore

    with flask_app.app_context():
        store = firestore.client()
        raw_rows = [
            item.to_dict() or {}
            for item in store.collection("prediction_market_snapshots")
            .where("record_type", "==", "pregame_market_consensus")
            .stream()
        ]

    # Use the earliest complete snapshot for a player/market/game.  Multiple
    # refreshes are valid observations operationally, but they are not
    # independent evidence for a Phase 2 calibration test.
    deduplicated: dict[tuple[str, str, str, str, float], dict] = {}
    for row in raw_rows:
        if row.get("sport") != "mlb" or row.get("consensus_method") != "median_devig_per_book_v2" or not row.get("settled_at"):
            continue
        probability, actual, line = row.get("fair_probability_over"), row.get("actual_value"), row.get("line")
        date = str(row.get("game_date") or "")
        if not all(isinstance(value, (int, float)) for value in (probability, actual, line)) or not date or actual == line:
            continue
        identity = (
            str(row.get("event_id") or ""),
            str(row.get("player") or "").casefold(),
            str(row.get("market_key") or ""),
            date,
            float(line),
        )
        previous = deduplicated.get(identity)
        if previous is None or str(row.get("taken_at") or "") < str(previous.get("taken_at") or ""):
            deduplicated[identity] = row

    rows = [
        {
            "date": str(row["game_date"]),
            "market": str(row.get("market") or "Other"),
            "probability": float(row["fair_probability_over"]) / 100,
            "outcome": int(float(row["actual_value"]) > float(row["line"])),
        }
        for row in deduplicated.values()
    ]
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
        calibrated_pairs: list[tuple[float, int]] = []
        if profile:
            for row in evaluation:
                band = profile["bands"].get(probability_band(row["probability"] * 100))
                calibrated = (
                    (band["over_rate"] * band["samples"] + profile["market_rate"] * PRIOR_STRENGTH) / (band["samples"] + PRIOR_STRENGTH)
                    if band else profile["market_rate"]
                )
                calibrated_pairs.append((calibrated, row["outcome"]))
        raw_brier = brier(raw_pairs)
        calibrated_brier = brier(calibrated_pairs)
        improvement = round(raw_brier - calibrated_brier, 4) if raw_brier is not None and calibrated_brier is not None else None
        training_samples = int(profile["samples"]) if profile else 0
        holdout_samples = len(evaluation)
        results[market] = {
            "training_samples": training_samples,
            "holdout_samples": holdout_samples,
            "raw_market_brier": raw_brier,
            "calibrated_market_brier": calibrated_brier,
            "brier_improvement": improvement,
            "eligible_for_future_manual_review": bool(
                training_samples >= MIN_TRAINING_SAMPLES
                and holdout_samples >= MIN_HOLDOUT_SAMPLES
                and improvement is not None
                and improvement >= MIN_BRIER_IMPROVEMENT
            ),
            "reason": "Requires enough independent forward samples and a lower untouched-holdout Brier score; this is not a selection or recommendation signal.",
        }

    print(json.dumps({
        "success": True,
        "isolated": True,
        "scope": "forward_captured_only",
        "training_end": args.training_end,
        "raw_eligible_rows": len(rows),
        "deduplicated_observations": len(deduplicated),
        "training_dates": sorted({row["date"] for row in training}),
        "holdout_dates": sorted({row["date"] for row in holdout}),
        "minimums": {
            "training_samples": MIN_TRAINING_SAMPLES,
            "holdout_samples": MIN_HOLDOUT_SAMPLES,
            "brier_improvement": MIN_BRIER_IMPROVEMENT,
        },
        "markets": results,
        "message": "Forward chronological calibration evaluation only. It does not create a model profile, generate recommendations, or change app output.",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
