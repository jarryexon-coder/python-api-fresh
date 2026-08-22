#!/usr/bin/env python3
"""Evaluate isolated NFL preseason multi-book game-market consensus.

This is a calibration/data-quality report only. It evaluates the market's
no-vig probabilities against verified final scores and never creates picks,
changes app output, or mixes preseason data into the regular-season model.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median


def decimal(price: float) -> float | None:
    if not price or price == 0:
        return None
    return 1 + price / 100 if price > 0 else 1 + 100 / abs(price)


def fair_probability(first: float, second: float) -> float | None:
    first_decimal, second_decimal = decimal(first), decimal(second)
    if not first_decimal or not second_decimal:
        return None
    first_implied, second_implied = 1 / first_decimal, 1 / second_decimal
    return first_implied / (first_implied + second_implied)


def probability_band(value: float) -> str:
    lower = int(value * 100 // 10) * 10
    return f"{lower}-{lower + 9}%"


def main() -> int:
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from app import app as flask_app
    from firebase_admin import firestore

    with flask_app.app_context():
        store = firestore.client()
        raw = [snapshot.to_dict() or {} for snapshot in store.collection("prediction_nfl_preseason_snapshots").where("record_type", "==", "historical_pregame_game_market_snapshot").stream()]

    observations: list[dict] = []
    skipped = 0
    for row in raw:
        final = row.get("final_score") if isinstance(row.get("final_score"), dict) else {}
        home_score, away_score = final.get("home_score"), final.get("away_score")
        if not isinstance(home_score, (int, float)) or not isinstance(away_score, (int, float)):
            skipped += 1
            continue
        teams = [part.strip() for part in str(row.get("game") or "").split("@")]
        if len(teams) != 2:
            skipped += 1
            continue
        away_name, home_name = teams
        books = row.get("bookmakers") if isinstance(row.get("bookmakers"), list) else []
        paired: dict[str, list[dict]] = defaultdict(list)
        for book in books:
            for market in book.get("markets", []) if isinstance(book, dict) else []:
                key = market.get("key") if isinstance(market, dict) else ""
                outcomes = market.get("outcomes", []) if isinstance(market, dict) else []
                if key == "h2h":
                    by_name = {str(item.get("name")): item for item in outcomes if isinstance(item, dict)}
                    home, away = by_name.get(home_name), by_name.get(away_name)
                    if home and away and isinstance(home.get("price"), (int, float)) and isinstance(away.get("price"), (int, float)):
                        probability = fair_probability(float(home["price"]), float(away["price"]))
                        if probability is not None:
                            paired["Moneyline (home win)"].append({"probability": probability, "outcome": int(home_score > away_score)})
                elif key == "spreads":
                    by_name = {str(item.get("name")): item for item in outcomes if isinstance(item, dict)}
                    home, away = by_name.get(home_name), by_name.get(away_name)
                    if home and away and all(isinstance(item.get("price"), (int, float)) for item in (home, away)) and isinstance(home.get("point"), (int, float)):
                        probability = fair_probability(float(home["price"]), float(away["price"]))
                        margin = home_score - away_score + float(home["point"])
                        if probability is not None and margin != 0:
                            paired["Spread (home cover)"].append({"probability": probability, "outcome": int(margin > 0)})
                elif key == "totals":
                    by_name = {str(item.get("name")).lower(): item for item in outcomes if isinstance(item, dict)}
                    over, under = by_name.get("over"), by_name.get("under")
                    if over and under and all(isinstance(item.get("price"), (int, float)) for item in (over, under)) and isinstance(over.get("point"), (int, float)):
                        probability = fair_probability(float(over["price"]), float(under["price"]))
                        total_margin = home_score + away_score - float(over["point"])
                        if probability is not None and total_margin != 0:
                            paired["Total (over)"].append({"probability": probability, "outcome": int(total_margin > 0)})
        # Books are not independent data. Collapse them to a median no-vig
        # probability per game/market before evaluating calibration.
        for market, values in paired.items():
            if not values:
                continue
            outcome = values[0]["outcome"]
            observations.append({"event_id": row.get("event_id"), "date": row.get("game_date"), "market": market, "probability": float(median([item["probability"] for item in values])), "outcome": outcome, "books": len(values)})

    def metrics(rows: list[dict]) -> dict:
        if not rows:
            return {"samples": 0, "actual_event_rate": None, "average_fair_probability": None, "brier_score": None, "average_book_count": None}
        return {
            "samples": len(rows),
            "actual_event_rate": round(sum(row["outcome"] for row in rows) / len(rows) * 100, 1),
            "average_fair_probability": round(sum(row["probability"] for row in rows) / len(rows) * 100, 1),
            "brier_score": round(sum((row["probability"] - row["outcome"]) ** 2 for row in rows) / len(rows), 4),
            "average_book_count": round(sum(row["books"] for row in rows) / len(rows), 2),
        }

    by_market: dict[str, list[dict]] = defaultdict(list)
    by_band: dict[str, list[dict]] = defaultdict(list)
    for row in observations:
        by_market[row["market"]].append(row)
        by_band[probability_band(row["probability"])].append(row)
    dates = sorted({str(row["date"]) for row in observations if row.get("date")})
    print(json.dumps({
        "success": True,
        "isolated": True,
        "season_phase": "preseason",
        "scope": "historical_nfl_game_markets_only",
        "records_found": len(raw),
        "verified_games": len({str(row.get("event_id")) for row in observations if row.get("event_id")}),
        "evaluated_game_market_observations": len(observations),
        "skipped_unverified_records": skipped,
        "date_range": {"first": dates[0] if dates else None, "last": dates[-1] if dates else None, "days": len(dates)},
        "overall": metrics(observations),
        "by_market": {market: metrics(rows) for market, rows in sorted(by_market.items())},
        "calibration_by_probability_band": {band: metrics(rows) for band, rows in sorted(by_band.items())},
        "message": "Preseason game-market calibration only. It is not a player-projection model, betting recommendation, or regular-season calibration.",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
