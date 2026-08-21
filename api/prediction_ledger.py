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
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import firebase_admin
from firebase_admin import firestore
from flask import Blueprint, g, jsonify, request
import requests


prediction_ledger_bp = Blueprint("prediction_ledger", __name__, url_prefix="/api/prediction-ledger")
VALID_SPORTS = {"mlb", "nfl", "nba"}
MIN_CALIBRATION_SAMPLE = 30
_memory_ledger: dict[str, dict[str, Any]] = {}
_memory_backtests: dict[str, dict[str, Any]] = {}
MLB_BACKTEST_MARKETS = {
    "batter_hits": ("Hits", "batting_h"),
    "batter_runs_scored": ("Runs Scored", "batting_r"),
    "batter_rbis": ("RBIs", "batting_rbi"),
    "batter_home_runs": ("Home Runs", "batting_hr"),
    "batter_total_bases": ("Total Bases", "batting_tb"),
    "pitcher_strikeouts": ("Strikeouts", "pitching_k"),
}


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


def _mlb_game_stats(game_id: Any) -> dict[str, dict[str, float]]:
    payload = _bdl_mlb("stats", {"game_ids[]": game_id, "per_page": 100})
    values: dict[str, dict[str, float]] = {}
    for row in payload.get("data", []):
        if not isinstance(row, dict):
            continue
        player = row.get("player") if isinstance(row.get("player"), dict) else {}
        name = player.get("full_name") or " ".join(filter(None, [player.get("first_name"), player.get("last_name")]))
        if name:
            values[_name_key(name)] = {field: _number(row.get(field)) or 0 for _, field in MLB_BACKTEST_MARKETS.values()}
    return values


def _mlb_historical_projection(player_name: str, market_key: str, before_date: str) -> float | None:
    """Last-ten-game average using only BDL game rows dated before the event."""
    search = _bdl_mlb("players", {"search": player_name, "per_page": 10})
    players = search.get("data", [])
    if not isinstance(players, list) or not players:
        return None
    def display_player_name(player: Any) -> str:
        return str(player.get("full_name") or " ".join(filter(None, [player.get("first_name"), player.get("last_name")])) or "") if isinstance(player, dict) else ""
    exact = next((player for player in players if _name_key(display_player_name(player)) == _name_key(player_name)), players[0])
    if not isinstance(exact, dict) or not exact.get("id"):
        return None
    season = int(before_date[:4])
    history = _bdl_mlb("stats", {"player_ids[]": exact["id"], "seasons[]": season, "per_page": 100})
    _, field = MLB_BACKTEST_MARKETS[market_key]
    previous: list[tuple[str, float]] = []
    for row in history.get("data", []):
        if not isinstance(row, dict):
            continue
        game = row.get("game") if isinstance(row.get("game"), dict) else {}
        played_on = _iso_date(game.get("date") or row.get("date"))
        value = _number(row.get(field))
        # A missing game date would allow future results into a historical model.
        if played_on and played_on < before_date and value is not None:
            previous.append((played_on, value))
    recent = [value for _, value in sorted(previous, reverse=True)[:10]]
    return round(sum(recent) / len(recent), 3) if len(recent) >= 5 else None


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
    try:
        max_events = max(1, min(int(request.args.get("max_events", 1)), 3))
    except ValueError:
        max_events = 1
    commit = str(request.args.get("commit") or "false").lower() == "true"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not markets:
        return jsonify({"error": "Provide date=YYYY-MM-DD and one or more supported MLB markets."}), 400
    if date >= datetime.now(timezone.utc).date().isoformat():
        return jsonify({"error": "Historical backtests require a completed past date."}), 400
    try:
        events = _historical_events(snapshot)[:max_events]
    except requests.RequestException as error:
        return jsonify({"error": f"Historical event lookup failed ({error.response.status_code if error.response else 'request error'})."}), 502
    preview = [{"event_id": event.get("id"), "game": f"{event.get('away_team')} @ {event.get('home_team')}", "commence_time": event.get("commence_time")} for event in events]
    if not commit:
        return jsonify({"success": True, "preview": True, "date": date, "snapshot": snapshot, "events": preview, "markets": markets, "estimated_historical_prop_credits": len(events) * len(markets) * 10, "message": "Review the event list and cost estimate, then rerun with commit=true to create isolated backtest records."})

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
                    projection = _mlb_historical_projection(player, key, date)
                    actual = actuals.get(_name_key(player), {}).get(MLB_BACKTEST_MARKETS[key][1])
                    if projection is None or actual is None:
                        skipped += 1
                        continue
                    side = "Over" if projection >= line else "Under"
                    record_id = hashlib.sha256(f"mlb-backtest|{event_id}|{player}|{key}|{line}|{snapshot}".encode()).hexdigest()[:32]
                    outcome = "push" if actual == line else "won" if (side == "Over" and actual > line) or (side == "Under" and actual < line) else "lost"
                    _backtest_store({"id": record_id, "isolation": "historical_backtest", "eligible_for_live_calibration": False, "sport": "mlb", "event_id": event_id, "game": f"{event.get('away_team')} @ {event.get('home_team')}", "player": player, "market": MLB_BACKTEST_MARKETS[key][0], "market_key": key, "line": line, "projection": projection, "side": side, "odds": prices.get(side.lower()), "actual_value": actual, "outcome": outcome, "snapshot": snapshot, "game_date": date, "model_version": "mlb-last10-pregame-v1", "line_source": "The Odds API historical event snapshot", "result_source": "BallDontLie MLB final game stats", "created_at": _now()})
                    imported += 1
            break  # one bookmaker avoids duplicate line versions
    return jsonify({"success": True, "preview": False, "isolated": True, "eligible_for_live_calibration": False, "date": date, "snapshot": snapshot, "events": preview, "imported": imported, "skipped": skipped, "errors": errors[:10], "message": "Backtest records are isolated from live calibration. Review their performance before promoting a validated model version."})


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
