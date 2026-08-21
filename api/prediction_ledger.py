"""Auditable prediction records and outcome calibration for the mobile app.

The ledger stores the *actual* line and model output shown to a customer.  It
never manufactures a result: a row becomes settled only through the protected
grading endpoint (or a future provider importer).  Calibration is therefore an
observed result, not a confidence formula.
"""
from __future__ import annotations

import hashlib
import os
import re
from math import sqrt
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import firebase_admin
from firebase_admin import firestore
from flask import Blueprint, g, jsonify, request
import requests

from api.mlb_model_v2 import american_to_decimal, evaluate_calibrated_prop, evaluate_directional_projection_prop, evaluate_market_relative_prop, evaluate_projection_relative_prop, evaluate_prop as evaluate_mlb_v2


prediction_ledger_bp = Blueprint("prediction_ledger", __name__, url_prefix="/api/prediction-ledger")
VALID_SPORTS = {"mlb", "nfl", "nba"}
MIN_CALIBRATION_SAMPLE = 30
_memory_ledger: dict[str, dict[str, Any]] = {}
_memory_backtests: dict[str, dict[str, Any]] = {}
_memory_calibrations: dict[str, dict[str, Any]] = {}
_mlb_recent_game_dates_cache: dict[str, dict[str, str]] = {}
MLB_BACKTEST_MARKETS = {
    "batter_hits": ("Hits", "hits"),
    "batter_runs_scored": ("Runs Scored", "runs"),
    "batter_rbis": ("RBIs", "rbi"),
    "batter_home_runs": ("Home Runs", "hr"),
    "batter_total_bases": ("Total Bases", "total_bases"),
    "pitcher_strikeouts": ("Strikeouts", "p_k"),
}
MIN_BACKTEST_PROMOTION_SAMPLE = 500
MIN_BACKTEST_HOLDOUT_SAMPLE = 150
MIN_BACKTEST_SIDE_SAMPLE = 75
MIN_BACKTEST_ODDS_COVERAGE = 0.90


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _odds_key() -> str | None:
    return os.getenv("THE_ODDS_API_KEY") or os.getenv("ODDS_API_KEY") or os.getenv("THEODDS_API_KEY")


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


def _import_authorized() -> bool:
    """Allow an administrator or the Railway scheduled job to settle records."""
    secret = os.getenv("PREDICTION_IMPORT_SECRET")
    supplied = request.headers.get("X-Prediction-Import-Key")
    return _admin() or bool(secret and supplied and supplied == secret)


def _name_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _pending_rows(sport: str | None = None) -> list[dict[str, Any]]:
    store = _store()
    if store:
        rows = [snapshot.to_dict() for snapshot in store.collection("prediction_ledger").where("status", "==", "pending").limit(500).stream()]
    else:
        rows = [row for row in _memory_ledger.values() if row.get("status") == "pending"]
    return [row for row in rows if not sport or row.get("sport") == sport]


def _set_result(ledger_id: str, row: dict[str, Any], actual: float, source: str) -> str:
    line, side = _number(row.get("line")), row.get("side")
    outcome = "push" if actual == line else "won" if (side == "Over" and actual > line) or (side == "Under" and actual < line) else "lost"
    update = {"actual_value": actual, "outcome": outcome, "status": "graded", "graded_at": _now(), "result_source": source}
    store = _store()
    if store:
        store.collection("prediction_ledger").document(ledger_id).set(update, merge=True)
    else:
        _memory_ledger[ledger_id] = {**row, **update}
    return outcome


def _date_for_row(row: dict[str, Any]) -> str | None:
    value = str(row.get("commence_time") or "")[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    created = str(row.get("created_at") or "")[:10]
    return created if re.fullmatch(r"\d{4}-\d{2}-\d{2}", created) else None


def _bdl_nba_box_scores(date: str) -> dict[str, dict[str, dict[str, float]]]:
    key = os.getenv("BALLDONTLIE_API_KEY")
    if not key:
        return {}
    response = requests.get("https://api.balldontlie.io/nba/v1/box_scores", headers={"Authorization": key}, params={"date": date}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    boxes = payload.get("data", []) if isinstance(payload, dict) else []
    result: dict[str, dict[str, dict[str, float]]] = {}
    for box in boxes if isinstance(boxes, list) else []:
        game = box.get("game", box) if isinstance(box, dict) else {}
        if not isinstance(game, dict) or not str(game.get("status") or "").lower().startswith("final"):
            continue
        away = game.get("visitor_team", game.get("away_team", {})) if isinstance(game.get("visitor_team", game.get("away_team", {})), dict) else {}
        home = game.get("home_team", {}) if isinstance(game.get("home_team", {}), dict) else {}
        game_key = f"{away.get('abbreviation') or away.get('name') or 'Away'} @ {home.get('abbreviation') or home.get('name') or 'Home'}"
        players: dict[str, dict[str, float]] = {}
        for team_box in (box.get("visitor_team", {}), box.get("home_team", {}), box.get("visitor_team_stats", {}), box.get("home_team_stats", {})):
            roster = team_box.get("players", []) if isinstance(team_box, dict) else []
            for stat in roster if isinstance(roster, list) else []:
                player = stat.get("player", {}) if isinstance(stat, dict) else {}
                name = player.get("full_name") or " ".join(filter(None, [player.get("first_name"), player.get("last_name")])) if isinstance(player, dict) else ""
                if name:
                    players[_name_key(name)] = {"points": _number(stat.get("pts")) or 0, "rebounds": _number(stat.get("reb")) or 0, "assists": _number(stat.get("ast")) or 0, "threes": _number(stat.get("fg3m")) or 0}
        if players:
            result[_name_key(game_key)] = players
    return result


def _tank_box_score(sport: str, row: dict[str, Any]) -> dict[str, dict[str, float]]:
    key = os.getenv("RAPIDAPI_KEY_TANK01") or os.getenv("RAPIDAPI_KEY")
    if not key:
        return {}
    date = _date_for_row(row)
    game = str(row.get("game") or "")
    teams = [part.strip() for part in game.split("@")] if "@" in game else []
    if not date or len(teams) != 2:
        return {}
    game_id = f"{date.replace('-', '')}_{teams[0]}@{teams[1]}"
    if sport == "nfl":
        host, endpoint = "tank01-nfl-live-in-game-real-time-statistics-nfl.p.rapidapi.com", "getNFLBoxScore"
    else:
        host, endpoint = "tank01-mlb-live-in-game-real-time-statistics.p.rapidapi.com", "getMLBBoxScore"
    response = requests.get(f"https://{host}/{endpoint}", headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": host}, params={"gameID": game_id}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    body = payload.get("body", payload) if isinstance(payload, dict) else {}
    status = str(body.get("gameStatus") or body.get("status") or "").lower() if isinstance(body, dict) else ""
    if "final" not in status:
        return {}
    raw = body.get("playerStats", body.get("players", {})) if isinstance(body, dict) else {}
    rows = raw.values() if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    result: dict[str, dict[str, float]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        name = item.get("longName") or item.get("playerName") or item.get("name")
        if not name:
            continue
        passing = item.get("Passing", {}) if isinstance(item.get("Passing"), dict) else {}
        rushing = item.get("Rushing", {}) if isinstance(item.get("Rushing"), dict) else {}
        receiving = item.get("Receiving", {}) if isinstance(item.get("Receiving"), dict) else {}
        batting = item.get("Batting", item.get("batting", {})) if isinstance(item.get("Batting", item.get("batting", {})), dict) else {}
        pitching = item.get("Pitching", item.get("pitching", {})) if isinstance(item.get("Pitching", item.get("pitching", {})), dict) else {}
        result[_name_key(name)] = {
            "passing yards": _number(passing.get("passYds")) or 0, "passing touchdowns": _number(passing.get("passTD")) or 0,
            "rushing yards": _number(rushing.get("rushYds")) or 0, "receiving yards": _number(receiving.get("recYds")) or 0,
            "receptions": _number(receiving.get("receptions")) or 0,
            "hits": _number(batting.get("H", batting.get("hits"))) or 0, "runs scored": _number(batting.get("R", batting.get("runs"))) or 0,
            "rbis": _number(batting.get("RBI", batting.get("rbis"))) or 0, "home runs": _number(batting.get("HR", batting.get("homeRuns"))) or 0,
            "total bases": _number(batting.get("TB", batting.get("totalBases"))) or 0, "strikeouts": _number(pitching.get("K", pitching.get("strikeouts"))) or 0,
        }
    return result


def _bdl_mlb(path: str, params: dict[str, Any]) -> dict[str, Any]:
    key = os.getenv("BALLDONTLIE_API_KEY")
    if not key:
        raise RuntimeError("BALLDONTLIE_API_KEY is not configured")
    response = requests.get(f"https://api.balldontlie.io/mlb/v1/{path.lstrip('/')}", headers={"Authorization": key}, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _iso_date(value: Any) -> str:
    return str(value or "")[:10]


def _mlb_team_name(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get("display_name") or value.get("full_name") or " ".join(filter(None, [value.get("location"), value.get("name")])) or value.get("name") or "")


def _mlb_game_for_event(date: str, event: dict[str, Any]) -> dict[str, Any] | None:
    payload = _bdl_mlb("games", {"dates[]": date, "per_page": 100})
    away_key, home_key = _name_key(event.get("away_team")), _name_key(event.get("home_team"))
    for game in payload.get("data", []):
        if not isinstance(game, dict):
            continue
        away = _name_key(_mlb_team_name(game.get("away_team") or game.get("visitor_team")))
        home = _name_key(_mlb_team_name(game.get("home_team")))
        if away == away_key and home == home_key:
            return game
    return None


def _mlb_game_stats(game_id: Any) -> dict[str, dict[str, Any]]:
    payload = _bdl_mlb("stats", {"game_ids[]": game_id, "per_page": 100})
    values: dict[str, dict[str, float]] = {}
    for row in payload.get("data", []):
        if not isinstance(row, dict):
            continue
        player = row.get("player") if isinstance(row.get("player"), dict) else {}
        name = player.get("full_name") or " ".join(filter(None, [player.get("first_name"), player.get("last_name")]))
        if name:
            values[_name_key(name)] = {"_player_id": player.get("id"), **{field: _number(row.get(field)) or 0 for _, field in MLB_BACKTEST_MARKETS.values()}}
    return values


def _mlb_recent_game_dates(before_date: str) -> dict[str, str]:
    """Map only the prior 21 days of game IDs, avoiding a slow season-wide scan."""
    cached = _mlb_recent_game_dates_cache.get(before_date)
    if cached is not None:
        return cached
    result: dict[str, str] = {}
    target = datetime.fromisoformat(before_date).date()
    dates = [(target - timedelta(days=offset)).isoformat() for offset in range(1, 22)]
    cursor: Any = None
    for _ in range(5):
        params: dict[str, Any] = {"dates[]": dates, "per_page": 100}
        if cursor is not None:
            params["cursor"] = cursor
        payload = _bdl_mlb("games", params)
        rows = payload.get("data", [])
        for game in rows if isinstance(rows, list) else []:
            if isinstance(game, dict) and game.get("id") and _iso_date(game.get("date")):
                result[str(game["id"])] = _iso_date(game.get("date"))
        cursor = payload.get("meta", {}).get("next_cursor") if isinstance(payload.get("meta"), dict) else None
        if not cursor or not rows:
            break
    _mlb_recent_game_dates_cache[before_date] = result
    return result


def _mlb_historical_projection(player_name: str, market_key: str, before_date: str, player_id: Any = None) -> tuple[float | None, int]:
    """Last-ten-game average using only BDL game rows dated before the event."""
    resolved_id = player_id
    if not resolved_id:
        search = _bdl_mlb("players", {"search": player_name, "per_page": 10})
        players = search.get("data", [])
        if not isinstance(players, list) or not players:
            return None, 0
        def display_player_name(player: Any) -> str:
            return str(player.get("full_name") or " ".join(filter(None, [player.get("first_name"), player.get("last_name")])) or "") if isinstance(player, dict) else ""
        exact = next((player for player in players if _name_key(display_player_name(player)) == _name_key(player_name)), players[0])
        if not isinstance(exact, dict) or not exact.get("id"):
            return None, 0
        resolved_id = exact["id"]
    season = int(before_date[:4])
    history = _bdl_mlb("stats", {"player_ids[]": resolved_id, "seasons[]": season, "per_page": 100})
    _, field = MLB_BACKTEST_MARKETS[market_key]
    game_dates = _mlb_recent_game_dates(before_date)
    previous: list[tuple[str, float]] = []
    for row in history.get("data", []):
        if not isinstance(row, dict):
            continue
        game = row.get("game") if isinstance(row.get("game"), dict) else {}
        played_on = _iso_date(game.get("date") or row.get("date")) or game_dates.get(str(row.get("game_id") or ""), "")
        value = _number(row.get(field))
        # A missing game date would allow future results into a historical model.
        if played_on and played_on < before_date and value is not None:
            previous.append((played_on, value))
    recent = [value for _, value in sorted(previous, reverse=True)[:10]]
    return (round(sum(recent) / len(recent), 3), len(recent)) if len(recent) >= 5 else (None, len(recent))


def _historical_events(snapshot: str) -> list[dict[str, Any]]:
    key = _odds_key()
    if not key:
        raise RuntimeError("THE_ODDS_API_KEY is not configured")
    response = requests.get("https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/events", params={"apiKey": key, "date": snapshot}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", payload) if isinstance(payload, dict) else []
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def _historical_mlb_props(event_id: str, snapshot: str, markets: list[str]) -> dict[str, Any]:
    response = requests.get(
        f"https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/events/{event_id}/odds",
        params={"apiKey": _odds_key(), "date": snapshot, "regions": "us", "markets": ",".join(markets), "oddsFormat": "american"}, timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    return data if isinstance(data, dict) else {}


def _backtest_store(record: dict[str, Any]) -> None:
    store = _store()
    if store:
        store.collection("prediction_backtest_ledger").document(record["id"]).set(record, merge=True)
    else:
        _memory_backtests[record["id"]] = record


def _bucket(value: float, step: float) -> str:
    return str(round(round(value / step) * step, 2)).replace(".", "_").replace("-", "neg_")


def _calibration_key(market_key: str, line: float, projection: float | None = None) -> str:
    base = f"{market_key}__l_{_bucket(line, 0.5)}"
    return f"{base}__p_{_bucket(projection, 0.2)}" if projection is not None else base


def _load_v22_profile() -> dict[str, Any] | None:
    store = _store()
    if store:
        snapshot = store.collection("prediction_model_calibrations").document("mlb-v2.2").get()
        return snapshot.to_dict() if snapshot.exists else None
    return _memory_calibrations.get("mlb-v2.2")


def _load_profile(profile_id: str) -> dict[str, Any] | None:
    store = _store()
    if store:
        snapshot = store.collection("prediction_model_calibrations").document(profile_id).get()
        return snapshot.to_dict() if snapshot.exists else None
    return _memory_calibrations.get(profile_id)


def _v22_over_probability(profile: dict[str, Any], market_key: str, line: float, projection: float) -> float | None:
    groups = profile.get("groups") if isinstance(profile.get("groups"), dict) else {}
    for key in (_calibration_key(market_key, line, projection), _calibration_key(market_key, line), market_key, "global"):
        group = groups.get(key)
        if isinstance(group, dict) and _number(group.get("probability_over")) is not None:
            return float(group["probability_over"])
    return None


def _fair_over_probability(over_odds: Any, under_odds: Any) -> float | None:
    over, under = american_to_decimal(over_odds), american_to_decimal(under_odds)
    if over is None or under is None:
        return None
    over_implied, under_implied = 1 / over, 1 / under
    return over_implied / (over_implied + under_implied)


def _v23_residual(profile: dict[str, Any], market_key: str, line: float, projection: float) -> float | None:
    groups = profile.get("groups") if isinstance(profile.get("groups"), dict) else {}
    for key in (_calibration_key(market_key, line, projection), _calibration_key(market_key, line), market_key, "global"):
        group = groups.get(key)
        if isinstance(group, dict) and _number(group.get("market_relative_over_residual")) is not None:
            return float(group["market_relative_over_residual"])
    return None


@prediction_ledger_bp.post("/backtest/mlb/v2.2/calibrate")
def calibrate_mlb_v22():
    """Freeze an empirical V2.2 training profile from pre-cutoff V1 results."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    training_end = str(request.args.get("training_end") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", training_end):
        return jsonify({"error": "Provide training_end=YYYY-MM-DD for the frozen V2.2 training window."}), 400
    source = [record for record in _mlb_backtest_records("mlb-last10-pregame-v1") if str(record.get("game_date") or "") <= training_end and _number(record.get("projection")) is not None and _number(record.get("line")) is not None]
    if len(source) < 100:
        return jsonify({"error": "At least 100 settled V1 records are required before calibration.", "records": len(source)}), 409
    grouped: dict[str, list[int]] = defaultdict(list)
    for record in source:
        projection, line = float(record["projection"]), float(record["line"])
        won_over = int(float(record.get("actual_value") or 0) > line)
        market = str(record.get("market_key") or "batter_hits")
        grouped["global"].append(won_over)
        grouped[market].append(won_over)
        grouped[_calibration_key(market, line)].append(won_over)
        grouped[_calibration_key(market, line, projection)].append(won_over)
    groups: dict[str, dict[str, Any]] = {}
    for key, outcomes in grouped.items():
        wins, samples = sum(outcomes), len(outcomes)
        # Beta(10, 10) shrinkage makes small projection bins fall back toward
        # a neutral probability instead of manufacturing extreme confidence.
        groups[key] = {"samples": samples, "over_wins": wins, "probability_over": round((wins + 10) / (samples + 20), 5)}
    profile = {"id": "mlb-v2.2", "model_version": "mlb-empirical-probability-ev-v2.2", "training_end": training_end, "training_samples": len(source), "source_model_version": "mlb-last10-pregame-v1", "groups": groups, "created_at": _now(), "frozen": True}
    store = _store()
    if store:
        store.collection("prediction_model_calibrations").document("mlb-v2.2").set(profile)
    else:
        _memory_calibrations["mlb-v2.2"] = profile
    return jsonify({"success": True, "model": "v2.2", "training_end": training_end, "training_samples": len(source), "groups": len(groups), "message": "Frozen profile created. Only import V2.2 backtests dated after training_end."})


@prediction_ledger_bp.post("/backtest/mlb/v2.3/calibrate")
def calibrate_mlb_v23():
    """Freeze V2.3 market-relative residuals from pre-cutoff V1 outcomes."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    training_end = str(request.args.get("training_end") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", training_end):
        return jsonify({"error": "Provide training_end=YYYY-MM-DD for the frozen V2.3 training window."}), 400
    source = [record for record in _mlb_backtest_records("mlb-last10-pregame-v1") if str(record.get("game_date") or "") <= training_end and _number(record.get("projection")) is not None and _number(record.get("line")) is not None and _fair_over_probability(record.get("over_odds"), record.get("under_odds")) is not None]
    if len(source) < 100:
        return jsonify({"error": "At least 100 settled, two-sided V1 records are required before calibration.", "records": len(source)}), 409
    grouped: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for record in source:
        projection, line = float(record["projection"]), float(record["line"])
        market = str(record.get("market_key") or "batter_hits")
        outcome_over = int(float(record.get("actual_value") or 0) > line)
        fair_over = _fair_over_probability(record.get("over_odds"), record.get("under_odds"))
        if fair_over is None:
            continue
        for key in ("global", market, _calibration_key(market, line), _calibration_key(market, line, projection)):
            grouped[key].append((outcome_over, fair_over))
    groups: dict[str, dict[str, Any]] = {}
    for key, observations in grouped.items():
        samples = len(observations)
        wins = sum(outcome for outcome, _ in observations)
        fair_sum = sum(fair for _, fair in observations)
        # Shrink any apparent deviation from the historical fair market toward
        # zero.  A 30-observation prior prevents thin bins from dominating.
        residual = (wins - fair_sum) / (samples + 30)
        groups[key] = {"samples": samples, "over_wins": wins, "fair_over_sum": round(fair_sum, 5), "market_relative_over_residual": round(residual, 5)}
    profile = {"id": "mlb-v2.3", "model_version": "mlb-market-relative-ev-v2.3", "training_end": training_end, "training_samples": len(source), "source_model_version": "mlb-last10-pregame-v1", "groups": groups, "created_at": _now(), "frozen": True}
    store = _store()
    if store:
        store.collection("prediction_model_calibrations").document("mlb-v2.3").set(profile)
    else:
        _memory_calibrations["mlb-v2.3"] = profile
    return jsonify({"success": True, "model": "v2.3", "training_end": training_end, "training_samples": len(source), "groups": len(groups), "message": "Frozen market-relative profile created. Only import V2.3 backtests dated after training_end."})


def _mlb_backtest_records(model_version: str | None = None) -> list[dict[str, Any]]:
    store = _store()
    if store:
        records = [snapshot.to_dict() for snapshot in store.collection("prediction_backtest_ledger").where("sport", "==", "mlb").limit(1500).stream()]
    else:
        records = list(_memory_backtests.values())
    return [record for record in records if record.get("isolation") == "historical_backtest" and record.get("outcome") in {"won", "lost", "push"} and (model_version is None or record.get("model_version") == model_version)]


def _american_profit(odds: Any, outcome: str) -> float | None:
    price = _number(odds)
    if price is None or price == 0:
        return None
    if outcome == "push":
        return 0.0
    if outcome == "lost":
        return -1.0
    return round(price / 100.0 if price > 0 else 100.0 / abs(price), 4)


def _wilson_lower_bound(wins: int, decided: int) -> float | None:
    if not decided:
        return None
    z = 1.96
    proportion = wins / decided
    denominator = 1 + z * z / decided
    centre = proportion + z * z / (2 * decided)
    margin = z * sqrt((proportion * (1 - proportion) + z * z / (4 * decided)) / decided)
    return round((centre - margin) / denominator * 100, 1)


def _backtest_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(item.get("outcome") == "won" for item in items)
    losses = sum(item.get("outcome") == "lost" for item in items)
    pushes = sum(item.get("outcome") == "push" for item in items)
    decided = wins + losses
    profits = [_american_profit(item.get("odds"), str(item.get("outcome"))) for item in items]
    priced = [profit for profit in profits if profit is not None]
    odds_coverage = round(len(priced) / len(items), 3) if items else 0.0
    units = round(sum(priced), 3) if priced else None
    roi = round(sum(priced) / len(priced) * 100, 2) if priced else None
    return {
        "samples": len(items), "wins": wins, "losses": losses, "pushes": pushes,
        "hit_rate": round(wins / decided * 100, 1) if decided else None,
        "wilson_lower_hit_rate": _wilson_lower_bound(wins, decided),
        "odds_coverage": odds_coverage, "profit_units": units, "roi_percent": roi,
    }


def _mean(items: list[dict[str, Any]], field: str) -> float | None:
    values = [_number(item.get(field)) for item in items]
    usable = [value for value in values if value is not None]
    return round(sum(usable) / len(usable), 3) if usable else None


def _diagnostic_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    gaps = [
        float(record["projection"]) - float(record["line"])
        for record in items
        if _number(record.get("projection")) is not None and _number(record.get("line")) is not None
    ]
    return {
        **_backtest_metrics(items),
        "average_expected_value": _mean(items, "expected_value"),
        "average_selected_probability": _mean(items, "model_probability"),
        "average_selected_odds": _mean(items, "odds"),
        "average_projection_minus_line": round(sum(gaps) / len(gaps), 3) if gaps else None,
    }


def _mlb_backtest_diagnostics(model_version: str) -> dict[str, Any]:
    """Read-only analysis of selection behavior; it cannot tune any model."""
    all_records = _mlb_backtest_records(model_version)
    candidates = [record for record in all_records if record.get("candidate") is True]
    by_side: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_ev_band: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_gap_band: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_odds_band: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in candidates:
        by_side[str(record.get("side") or "Unknown")].append(record)
        ev = _number(record.get("expected_value"))
        ev_label = "Unknown" if ev is None else "5–7.49%" if ev < 0.075 else "7.5–9.99%" if ev < 0.10 else "10%+"
        by_ev_band[ev_label].append(record)
        projection, line = _number(record.get("projection")), _number(record.get("line"))
        gap = projection - line if projection is not None and line is not None else None
        gap_label = "Unknown" if gap is None else "≤ -0.25" if gap <= -0.25 else "-0.25 to -0.10" if gap <= -0.10 else "-0.10 to 0.10" if gap <= 0.10 else "0.10 to 0.25" if gap <= 0.25 else "> 0.25"
        by_gap_band[gap_label].append(record)
        odds = _number(record.get("odds"))
        odds_label = "Unknown" if odds is None else "≤ -200" if odds <= -200 else "-199 to -151" if odds <= -151 else "-150 to -111" if odds <= -111 else "-110 to +100" if odds <= 100 else "+101 or longer"
        by_odds_band[odds_label].append(record)
    side_counts = {side: len(rows) for side, rows in by_side.items()}
    warnings: list[str] = []
    if candidates and max(side_counts.values(), default=0) / len(candidates) >= 0.80:
        warnings.append("Selection is concentrated on one side; investigate projection-versus-market calibration before changing thresholds.")
    if _backtest_metrics(candidates).get("roi_percent") is not None and _backtest_metrics(candidates)["roi_percent"] <= 0:
        warnings.append("Candidate ROI is non-positive; the model should remain research-only.")
    return {
        "success": True,
        "isolated": True,
        "eligible_for_live_calibration": False,
        "model_version": model_version,
        "all_evaluated_props": len(all_records),
        "candidate_props": len(candidates),
        "non_candidate_props": len(all_records) - len(candidates),
        "overall_candidates": _diagnostic_summary(candidates),
        "by_side": {name: _diagnostic_summary(rows) for name, rows in sorted(by_side.items())},
        "by_expected_value_band": {name: _diagnostic_summary(rows) for name, rows in by_ev_band.items()},
        "by_projection_minus_line_band": {name: _diagnostic_summary(rows) for name, rows in by_gap_band.items()},
        "by_selected_odds_band": {name: _diagnostic_summary(rows) for name, rows in by_odds_band.items()},
        "warnings": warnings,
        "message": "Diagnostic report only. It does not modify thresholds, calibration, or live predictions.",
    }


def _mlb_backtest_evaluation(model_version: str = "mlb-last10-pregame-v1") -> dict[str, Any]:
    all_records = _mlb_backtest_records(model_version)
    candidate_only = model_version.startswith(("mlb-probability-ev-v2", "mlb-empirical-probability-ev-v2", "mlb-market-relative-ev-v2", "mlb-projection-relative-ev-v2", "mlb-directional-projection-ev-v2"))
    records = [record for record in all_records if record.get("candidate") is True] if candidate_only else all_records
    ordered_dates = sorted({str(record.get("game_date") or "") for record in records if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(record.get("game_date") or ""))})
    holdout_dates = set(ordered_dates[-max(1, round(len(ordered_dates) * 0.2)):]) if ordered_dates else set()
    holdout = [record for record in records if record.get("game_date") in holdout_dates]
    training = [record for record in records if record.get("game_date") not in holdout_dates]
    by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_market[str(record.get("market") or "Other")].append(record)
    overall = _backtest_metrics(records)
    side_metrics = {side: _backtest_metrics([record for record in records if record.get("side") == side]) for side in ("Over", "Under")}
    holdout_metrics = _backtest_metrics(holdout)
    reasons: list[str] = []
    if overall["samples"] < MIN_BACKTEST_PROMOTION_SAMPLE:
        reasons.append(f"Needs at least {MIN_BACKTEST_PROMOTION_SAMPLE} total settled samples.")
    if holdout_metrics["samples"] < MIN_BACKTEST_HOLDOUT_SAMPLE:
        reasons.append(f"Needs at least {MIN_BACKTEST_HOLDOUT_SAMPLE} chronological holdout samples.")
    for side, metrics in side_metrics.items():
        if metrics["samples"] < MIN_BACKTEST_SIDE_SAMPLE:
            reasons.append(f"Needs at least {MIN_BACKTEST_SIDE_SAMPLE} {side.lower()} samples.")
    if overall["odds_coverage"] < MIN_BACKTEST_ODDS_COVERAGE:
        reasons.append("Needs odds on at least 90% of settled predictions.")
    if overall["roi_percent"] is None or overall["roi_percent"] <= 0:
        reasons.append("Full-sample ROI must be positive after listed odds.")
    if holdout_metrics["roi_percent"] is None or holdout_metrics["roi_percent"] <= 0:
        reasons.append("Chronological holdout ROI must be positive after listed odds.")
    model_versions = sorted({str(record.get("model_version") or "unknown") for record in records})
    return {
        "success": True, "isolated": True, "eligible_for_live_calibration": False,
        "model_versions": model_versions, "evaluated_model_version": model_version,
        "evaluated_candidates_only": candidate_only, "all_evaluated_props": len(all_records), "candidate_props": len(records), "overall": overall,
        "training": _backtest_metrics(training), "holdout": {**holdout_metrics, "dates": sorted(holdout_dates)},
        "by_side": side_metrics,
        "by_market": {market: _backtest_metrics(items) for market, items in by_market.items()},
        "promotion_gate": {
            "eligible_for_manual_review": not reasons,
            "automatic_live_promotion": False,
            "reasons": reasons,
            "requirements": {"total_samples": MIN_BACKTEST_PROMOTION_SAMPLE, "holdout_samples": MIN_BACKTEST_HOLDOUT_SAMPLE, "per_side_samples": MIN_BACKTEST_SIDE_SAMPLE, "odds_coverage": MIN_BACKTEST_ODDS_COVERAGE},
        },
        "message": "Evaluation uses a chronological holdout and listed odds. It cannot change live predictions automatically.",
    }


@prediction_ledger_bp.post("/backtest/mlb")
def historical_mlb_backtest():
    """Import an isolated, point-in-time MLB backtest sample.

    This endpoint is deliberately manual and preview-first because historical
    player props are billed per event/market by the odds provider.
    """
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    date = str(request.args.get("date") or "")
    snapshot = str(request.args.get("snapshot") or f"{date}T15:00:00Z")
    requested_markets = [value.strip() for value in str(request.args.get("markets") or "batter_hits").split(",") if value.strip()]
    markets = [market for market in requested_markets if market in MLB_BACKTEST_MARKETS]
    model = str(request.args.get("model") or "v1").lower()
    try:
        max_events = max(1, min(int(request.args.get("max_events", 1)), 3))
    except ValueError:
        max_events = 1
    commit = str(request.args.get("commit") or "false").lower() == "true"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not markets or model not in {"v1", "v2", "v2.1", "v2.2", "v2.3", "v2.4", "v2.5"}:
        return jsonify({"error": "Provide date=YYYY-MM-DD and one or more supported MLB markets."}), 400
    if not snapshot.startswith(f"{date}T"):
        return jsonify({"error": "snapshot must be a pregame UTC timestamp on the same date as date (for example, 2026-08-14T13:00:00Z)."}), 400
    if date >= datetime.now(timezone.utc).date().isoformat():
        return jsonify({"error": "Historical backtests require a completed past date."}), 400
    v22_profile = _load_v22_profile() if model == "v2.2" else None
    v23_profile = _load_profile("mlb-v2.3") if model == "v2.3" else None
    if model == "v2.2" and (not v22_profile or str(v22_profile.get("training_end") or "") >= date):
        return jsonify({"error": "V2.2 requires a frozen profile with training_end before the imported game date."}), 409
    if model == "v2.3" and (not v23_profile or str(v23_profile.get("training_end") or "") >= date):
        return jsonify({"error": "V2.3 requires a frozen profile with training_end before the imported game date."}), 409
    try:
        events = _historical_events(snapshot)[:max_events]
    except requests.RequestException as error:
        return jsonify({"error": f"Historical event lookup failed ({error.response.status_code if error.response else 'request error'})."}), 502
    preview = [{"event_id": event.get("id"), "game": f"{event.get('away_team')} @ {event.get('home_team')}", "commence_time": event.get("commence_time")} for event in events]
    if not commit:
        return jsonify({"success": True, "preview": True, "model": model, "date": date, "snapshot": snapshot, "events": preview, "markets": markets, "estimated_historical_prop_credits": len(events) * len(markets) * 10, "message": "Review the event list and cost estimate, then rerun with commit=true to create isolated backtest records."})

    imported = skipped = 0
    errors: list[str] = []
    for event in events:
        event_id = str(event.get("id") or "")
        if not event_id:
            continue
        try:
            game = _mlb_game_for_event(date, event)
            if not game or "final" not in str(game.get("status") or "").lower():
                skipped += 1
                continue
            actuals = _mlb_game_stats(game.get("id"))
            historical = _historical_mlb_props(event_id, snapshot, markets)
        except (requests.RequestException, RuntimeError) as error:
            errors.append(f"{event_id}: {error}")
            continue
        # V2.3+ needs a genuine two-sided price. Historical feeds occasionally
        # expose only one side at a bookmaker, so scan later books until the
        # first complete pair for each player/line instead of treating the
        # first bookmaker as authoritative.
        two_sided_complete_pairs: set[tuple[str, str, float]] = set()
        for bookmaker in historical.get("bookmakers", []) if isinstance(historical, dict) else []:
            if not isinstance(bookmaker, dict):
                continue
            for market in bookmaker.get("markets", []):
                key = str(market.get("key") or "")
                if key not in markets or not isinstance(market, dict):
                    continue
                pairs: dict[tuple[str, float], dict[str, float | None]] = {}
                for outcome in market.get("outcomes", []):
                    if not isinstance(outcome, dict):
                        continue
                    player, line = str(outcome.get("description") or "").strip(), _number(outcome.get("point"))
                    side = str(outcome.get("name") or "").lower()
                    if player and line is not None and side in {"over", "under"}:
                        pairs.setdefault((player, line), {"over": None, "under": None})[side] = _number(outcome.get("price"))
                for (player, line), prices in pairs.items():
                    pair_identity = (key, _name_key(player), line)
                    if model in {"v2.3", "v2.4", "v2.5"}:
                        if prices.get("over") is None or prices.get("under") is None:
                            continue
                        if pair_identity in two_sided_complete_pairs:
                            continue
                    actual_row = actuals.get(_name_key(player), {})
                    projection, sample_games = _mlb_historical_projection(player, key, date, actual_row.get("_player_id"))
                    actual = actual_row.get(MLB_BACKTEST_MARKETS[key][1])
                    if projection is None or actual is None:
                        skipped += 1
                        continue
                    if model in {"v2.3", "v2.4", "v2.5"}:
                        two_sided_complete_pairs.add(pair_identity)
                    v2_version = "mlb-probability-ev-v2.1" if model == "v2.1" else "mlb-probability-ev-v2"
                    calibrated_probability = _v22_over_probability(v22_profile, key, line, projection) if v22_profile else None
                    relative_residual = _v23_residual(v23_profile, key, line, projection) if v23_profile else None
                    model_output = evaluate_directional_projection_prop(season_rate=projection, line=line, over_odds=prices.get("over"), under_odds=prices.get("under"), sample_games=sample_games) if model == "v2.5" else evaluate_projection_relative_prop(season_rate=projection, line=line, over_odds=prices.get("over"), under_odds=prices.get("under"), sample_games=sample_games) if model == "v2.4" else evaluate_market_relative_prop(season_rate=projection, line=line, over_odds=prices.get("over"), under_odds=prices.get("under"), sample_games=sample_games, historical_residual=relative_residual) if model == "v2.3" else evaluate_calibrated_prop(season_rate=projection, line=line, over_odds=prices.get("over"), under_odds=prices.get("under"), sample_games=sample_games, calibrated_over_probability=calibrated_probability) if model == "v2.2" else evaluate_mlb_v2(season_rate=projection, line=line, over_odds=prices.get("over"), under_odds=prices.get("under"), sample_games=sample_games if model == "v2.1" else None, model_version=v2_version) if model in {"v2", "v2.1"} else None
                    if model in {"v2", "v2.1", "v2.2", "v2.3", "v2.4", "v2.5"} and not model_output:
                        skipped += 1
                        continue
                    side = str(model_output["selected_side"]) if model_output else "Over" if projection >= line else "Under"
                    model_version = str(model_output["model_version"]) if model_output else "mlb-last10-pregame-v1"
                    stored_projection = float(model_output["projection"]) if model_output else projection
                    record_id = hashlib.sha256(f"mlb-backtest|{model_version}|{event_id}|{player}|{key}|{line}|{snapshot}".encode()).hexdigest()[:32]
                    outcome = "push" if actual == line else "won" if (side == "Over" and actual > line) or (side == "Under" and actual < line) else "lost"
                    _backtest_store({"id": record_id, "isolation": "historical_backtest", "eligible_for_live_calibration": False, "sport": "mlb", "event_id": event_id, "game": f"{event.get('away_team')} @ {event.get('home_team')}", "player": player, "market": MLB_BACKTEST_MARKETS[key][0], "market_key": key, "line": line, "projection": stored_projection, "side": side, "odds": prices.get(side.lower()), "over_odds": prices.get("over"), "under_odds": prices.get("under"), "actual_value": actual, "outcome": outcome, "snapshot": snapshot, "game_date": date, "model_version": model_version, "model_probability": model_output.get("selected_probability") if model_output else None, "expected_value": model_output.get("expected_value") if model_output else None, "candidate": model_output.get("candidate") if model_output else None, "line_source": "The Odds API historical event snapshot", "result_source": "BallDontLie MLB final game stats", "created_at": _now()})
                    imported += 1
            if model not in {"v2.3", "v2.4", "v2.5"}:
                break  # one bookmaker avoids duplicate line versions
    return jsonify({"success": True, "preview": False, "isolated": True, "eligible_for_live_calibration": False, "date": date, "snapshot": snapshot, "events": preview, "imported": imported, "skipped": skipped, "errors": errors[:10], "message": "Backtest records are isolated from live calibration. Review their performance before promoting a validated model version."})


@prediction_ledger_bp.get("/backtest/mlb/summary")
def historical_mlb_backtest_summary():
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    model = str(request.args.get("model") or "v1").lower()
    versions = {"v1": "mlb-last10-pregame-v1", "v2": "mlb-probability-ev-v2", "v2.1": "mlb-probability-ev-v2.1", "v2.2": "mlb-empirical-probability-ev-v2.2", "v2.3": "mlb-market-relative-ev-v2.3", "v2.4": "mlb-projection-relative-ev-v2.4", "v2.5": "mlb-directional-projection-ev-v2.5"}
    if model not in versions:
        return jsonify({"error": "model must be v1, v2, v2.1, v2.2, v2.3, v2.4, or v2.5"}), 400
    records = _mlb_backtest_records(versions[model])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get("market") or "Other")].append(record)

    def result(items: list[dict[str, Any]]) -> dict[str, Any]:
        wins = sum(item.get("outcome") == "won" for item in items)
        losses = sum(item.get("outcome") == "lost" for item in items)
        pushes = sum(item.get("outcome") == "push" for item in items)
        decided = wins + losses
        return {"samples": len(items), "wins": wins, "losses": losses, "pushes": pushes, "hit_rate": round(wins / decided * 100, 1) if decided else None}

    return jsonify({"success": True, "isolated": True, "model": model, "eligible_for_live_calibration": False, "overall": result(records), "markets": {market: result(items) for market, items in grouped.items()}, "message": "Historical backtest summary only. It is not live-model calibration."})


@prediction_ledger_bp.get("/backtest/mlb/evaluation")
def historical_mlb_backtest_evaluation():
    """Evaluate the isolated model with odds-aware, chronological safeguards."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    model = str(request.args.get("model") or "v1").lower()
    versions = {"v1": "mlb-last10-pregame-v1", "v2": "mlb-probability-ev-v2", "v2.1": "mlb-probability-ev-v2.1", "v2.2": "mlb-empirical-probability-ev-v2.2", "v2.3": "mlb-market-relative-ev-v2.3", "v2.4": "mlb-projection-relative-ev-v2.4", "v2.5": "mlb-directional-projection-ev-v2.5"}
    if model not in versions:
        return jsonify({"error": "model must be v1, v2, v2.1, v2.2, v2.3, v2.4, or v2.5"}), 400
    return jsonify({**_mlb_backtest_evaluation(versions[model]), "model": model})


@prediction_ledger_bp.get("/backtest/mlb/diagnostics")
def historical_mlb_backtest_diagnostics():
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    model = str(request.args.get("model") or "v2.4").lower()
    versions = {"v1": "mlb-last10-pregame-v1", "v2": "mlb-probability-ev-v2", "v2.1": "mlb-probability-ev-v2.1", "v2.2": "mlb-empirical-probability-ev-v2.2", "v2.3": "mlb-market-relative-ev-v2.3", "v2.4": "mlb-projection-relative-ev-v2.4", "v2.5": "mlb-directional-projection-ev-v2.5"}
    if model not in versions:
        return jsonify({"error": "model must be v1, v2, v2.1, v2.2, v2.3, v2.4, or v2.5"}), 400
    return jsonify({**_mlb_backtest_diagnostics(versions[model]), "model": model})


@prediction_ledger_bp.post("/backtest/mlb/promotion")
def promote_historical_mlb_model():
    """Record a reviewed backtest decision; it never switches live logic itself."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    model = str(request.args.get("model") or "v1").lower()
    versions = {"v1": "mlb-last10-pregame-v1", "v2": "mlb-probability-ev-v2", "v2.1": "mlb-probability-ev-v2.1", "v2.2": "mlb-empirical-probability-ev-v2.2", "v2.3": "mlb-market-relative-ev-v2.3", "v2.4": "mlb-projection-relative-ev-v2.4", "v2.5": "mlb-directional-projection-ev-v2.5"}
    if model not in versions:
        return jsonify({"error": "model must be v1, v2, v2.1, v2.2, v2.3, v2.4, or v2.5"}), 400
    evaluation = _mlb_backtest_evaluation(versions[model])
    if not evaluation["promotion_gate"]["eligible_for_manual_review"]:
        return jsonify({"success": False, "error": "Promotion gate is not met.", "evaluation": evaluation}), 409
    payload = request.get_json(silent=True) or {}
    if payload.get("approve") is not True:
        return jsonify({"success": True, "approved": False, "evaluation": evaluation, "message": "Gate is eligible. Re-submit with JSON {\"approve\": true} after manual review."})
    record = {"sport": "mlb", "model": model, "model_versions": evaluation["model_versions"], "status": "approved_for_manual_live_integration", "approved_at": _now(), "evaluation": evaluation}
    store = _store()
    if store:
        store.collection("prediction_model_promotions").document(f"mlb-{model}").set(record)
    return jsonify({"success": True, "approved": True, "automatic_live_promotion": False, "message": "Decision recorded. Live integration remains a separate reviewed deployment."})


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


@prediction_ledger_bp.post("/import-results")
def import_results():
    """Nightly provider-backed settlement for recent pending NBA, NFL, and MLB rows."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    requested = str(request.args.get("sport") or "").lower()
    if requested and requested not in VALID_SPORTS:
        return jsonify({"error": "sport must be nba, nfl, or mlb"}), 400
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    rows = [row for row in _pending_rows(requested or None) if not row.get("created_at") or str(row.get("created_at")) >= cutoff.isoformat()]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        date = _date_for_row(row)
        if date:
            grouped[(str(row.get("sport")), date)].append(row)
    totals: dict[str, Any] = {"checked": len(rows), "graded": 0, "won": 0, "lost": 0, "push": 0, "pending": 0, "provider_errors": []}
    nba_cache: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    tank_cache: dict[str, dict[str, dict[str, float]]] = {}
    for (sport, date), pending in grouped.items():
        if sport == "nba":
            try:
                nba_cache[date] = _bdl_nba_box_scores(date)
            except requests.RequestException as error:
                totals["provider_errors"].append(f"nba {date}: {error.response.status_code if error.response else 'request failed'}")
                continue
        for row in pending:
            player_stats: dict[str, float] = {}
            source = ""
            try:
                if sport == "nba":
                    player_stats = nba_cache.get(date, {}).get(_name_key(row.get("game")), {}).get(_name_key(row.get("player")), {})
                    source = "BallDontLie NBA final box score"
                else:
                    cache_key = str(row.get("id"))
                    if cache_key not in tank_cache:
                        tank_cache[cache_key] = _tank_box_score(sport, row)
                    player_stats = tank_cache[cache_key].get(_name_key(row.get("player")), {})
                    source = f"Tank01 {sport.upper()} final box score"
            except requests.RequestException as error:
                totals["provider_errors"].append(f"{sport} {date}: {error.response.status_code if error.response else 'request failed'}")
                continue
            actual = player_stats.get(str(row.get("market") or "").lower())
            if actual is None:
                totals["pending"] += 1
                continue
            outcome = _set_result(str(row["id"]), row, actual, source)
            totals["graded"] += 1
            totals[outcome] += 1
    return jsonify({"success": True, "source": "verified final box scores", **totals, "run_at": _now()})


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
