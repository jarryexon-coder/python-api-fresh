"""Auditable prediction records and outcome calibration for the mobile app.

The ledger stores the *actual* line and model output shown to a customer.  It
never manufactures a result: a row becomes settled only through the protected
grading endpoint (or a future provider importer).  Calibration is therefore an
observed result, not a confidence formula.
"""
from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import firebase_admin
from firebase_admin import firestore
from flask import Blueprint, g, jsonify, request


prediction_ledger_bp = Blueprint("prediction_ledger", __name__, url_prefix="/api/prediction-ledger")
VALID_SPORTS = {"mlb", "nfl", "nba"}
MIN_CALIBRATION_SAMPLE = 30
_memory_ledger: dict[str, dict[str, Any]] = {}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _store():
    try:
        return firestore.client() if firebase_admin._apps else None
    except Exception:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _admin() -> bool:
    configured = {value.strip().lower() for value in os.getenv("ADMIN_EMAILS", "").split(",") if value.strip()}
    email = str(getattr(g, "user_email", "")).lower()
    return bool(email and email in configured)


def _normalise(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    sport = str(item.get("sport") or "").lower()
    line, projection = _number(item.get("line")), _number(item.get("projection"))
    side = str(item.get("side") or item.get("type") or "").title()
    player, market = str(item.get("player") or "").strip(), str(item.get("market") or item.get("stat") or "").strip()
    if sport not in VALID_SPORTS or line is None or projection is None or side not in {"Over", "Under"} or not player or not market:
        return None
    game = str(item.get("game") or "").strip()
    fingerprint = "|".join((sport, str(item.get("game_id") or game), player.lower(), market.lower(), f"{line:.3f}", side, str(item.get("commence_time") or "")[:10]))
    ledger_id = hashlib.sha256(fingerprint.encode()).hexdigest()[:32]
    return {
        "id": ledger_id, "sport": sport, "player": player, "team": str(item.get("team") or ""),
        "market": market, "game": game, "game_id": str(item.get("game_id") or ""),
        "commence_time": str(item.get("commence_time") or ""), "line": line, "projection": projection,
        "edge": _number(item.get("edge")), "confidence": _number(item.get("confidence")),
        "side": side, "odds": _number(item.get("odds")), "source": str(item.get("source") or ""),
    }


@prediction_ledger_bp.post("/record")
def record_predictions():
    payload = request.get_json(silent=True) or {}
    rows = payload.get("predictions", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return jsonify({"error": "predictions must be an array"}), 400
    accepted = [_normalise(row) for row in rows[:50]]
    accepted = [row for row in accepted if row]
    store = _store()
    viewer = str(getattr(g, "user_id", ""))
    for row in accepted:
        record = {**row, "last_seen_at": _now(), "viewer_id": viewer, "model_version": "live-line-v1"}
        if store:
            ref = store.collection("prediction_ledger").document(row["id"])
            snapshot = ref.get()
            existing = snapshot.to_dict() if snapshot.exists else None
            if not existing:
                record.update({"created_at": _now(), "status": "pending", "outcome": "pending", "actual_value": None})
            ref.set(record, merge=True)
        else:
            previous = _memory_ledger.get(row["id"], {})
            _memory_ledger[row["id"]] = {**previous, **record, "created_at": previous.get("created_at", _now()), "status": previous.get("status", "pending"), "outcome": previous.get("outcome", "pending"), "actual_value": previous.get("actual_value")}
    return jsonify({"success": True, "recorded": len(accepted)})


@prediction_ledger_bp.post("/grade")
def grade_predictions():
    if not _admin():
        return jsonify({"error": "Administrator access is required to grade predictions."}), 403
    payload = request.get_json(silent=True) or {}
    results = payload.get("results", []) if isinstance(payload, dict) else []
    if not isinstance(results, list):
        return jsonify({"error": "results must be an array"}), 400
    store, graded = _store(), 0
    for result in results[:100]:
        if not isinstance(result, dict):
            continue
        ledger_id, actual = str(result.get("ledger_id") or ""), _number(result.get("actual_value"))
        if not ledger_id or actual is None:
            continue
        current = store.collection("prediction_ledger").document(ledger_id).get().to_dict() if store else _memory_ledger.get(ledger_id)
        if not current:
            continue
        line, side = _number(current.get("line")), current.get("side")
        outcome = "push" if actual == line else "won" if (side == "Over" and actual > line) or (side == "Under" and actual < line) else "lost"
        update = {"actual_value": actual, "outcome": outcome, "status": "graded", "graded_at": _now(), "result_source": str(result.get("source") or "verified provider result")}
        if store:
            store.collection("prediction_ledger").document(ledger_id).set(update, merge=True)
        else:
            _memory_ledger[ledger_id] = {**current, **update}
        graded += 1
    return jsonify({"success": True, "graded": graded})


@prediction_ledger_bp.get("/calibration")
def calibration():
    sport = str(request.args.get("sport") or "").lower()
    if sport not in VALID_SPORTS:
        return jsonify({"error": "sport must be nba, nfl, or mlb"}), 400
    store = _store()
    if store:
        rows = [snapshot.to_dict() for snapshot in store.collection("prediction_ledger").where("sport", "==", sport).limit(1500).stream()]
    else:
        rows = [row for row in _memory_ledger.values() if row.get("sport") == sport]
    settled = [row for row in rows if row.get("status") == "graded" and row.get("outcome") in {"won", "lost"}]
    by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in settled:
        by_market[str(row.get("market") or "Other")].append(row)

    def summary(items: list[dict[str, Any]]) -> dict[str, Any]:
        wins = sum(1 for item in items if item.get("outcome") == "won")
        count = len(items)
        # Beta(10,10) shrinkage prevents tiny samples from masquerading as certainty.
        shrunk_rate = round(((wins + 10) / (count + 20)) * 100, 1) if count else None
        return {"settled_count": count, "wins": wins, "losses": count - wins, "hit_rate": round(wins / count * 100, 1) if count else None, "shrunk_hit_rate": shrunk_rate, "calibrated": count >= MIN_CALIBRATION_SAMPLE}

    return jsonify({"success": True, "sport": sport, "overall": summary(settled), "markets": {market: summary(items) for market, items in by_market.items()}, "minimum_sample": MIN_CALIBRATION_SAMPLE, "updated_at": _now()})
