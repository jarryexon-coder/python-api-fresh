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
from math import exp, log, sqrt
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

import firebase_admin
from firebase_admin import firestore
from flask import Blueprint, g, jsonify, request
import requests

from api.mlb_model_v2 import american_to_decimal, evaluate_calibrated_directional_prop, evaluate_calibrated_prop, evaluate_continuous_market_anchored_prop, evaluate_directional_projection_prop, evaluate_market_relative_prop, evaluate_projection_relative_prop, evaluate_prop as evaluate_mlb_v2, poisson_over_probability
from api.live_props import _mlb_projections


prediction_ledger_bp = Blueprint("prediction_ledger", __name__, url_prefix="/api/prediction-ledger")
VALID_SPORTS = {"mlb", "nfl", "nba", "wnba"}
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
WNBA_MARKETS = {
    "player_points": ("Points", "points"),
    "player_rebounds": ("Rebounds", "rebounds"),
    "player_assists": ("Assists", "assists"),
    "player_threes": ("3-Pointers Made", "threes"),
    "player_points_rebounds_assists": ("Points + Rebounds + Assists", "points_rebounds_assists"),
}
NCAAF_PROP_MARKETS = {
    "player_pass_yds": ("Passing Yards", "passing_yards"),
    "player_pass_tds": ("Passing Touchdowns", "passing_touchdowns"),
    "player_pass_interceptions": ("Passing Interceptions", "passing_interceptions"),
    "player_rush_yds": ("Rushing Yards", "rushing_yards"),
    "player_rush_tds": ("Rushing Touchdowns", "rushing_touchdowns"),
    "player_reception_yds": ("Receiving Yards", "receiving_yards"),
    "player_receptions": ("Receptions", "receptions"),
    "player_reception_tds": ("Receiving Touchdowns", "receiving_touchdowns"),
}
NFL_PRESEASON_GAME_MARKETS = {"h2h", "spreads", "totals"}
NFL_PRESEASON_MAX_SNAPSHOT_LEAD_HOURS = 16
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


def _eastern_sports_date(value: Any) -> str:
    """Use the league's calendar date, not a late game's following UTC date."""
    try:
        instant = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return instant.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    except ValueError:
        return str(value or "")[:10]


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


def _historical_mlb_moneyline_odds(event_id: str, snapshot: str) -> dict[str, Any]:
    response = requests.get(
        f"https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/events/{event_id}/odds",
        params={"apiKey": _odds_key(), "date": snapshot, "regions": "us", "markets": "h2h", "oddsFormat": "american"}, timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    return data if isinstance(data, dict) else {}


def _current_mlb_events() -> list[dict[str, Any]]:
    response = requests.get("https://api.the-odds-api.com/v4/sports/baseball_mlb/events", params={"apiKey": _odds_key()}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _current_mlb_props(event_id: str, markets: list[str]) -> dict[str, Any]:
    response = requests.get(
        f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{event_id}/odds",
        params={"apiKey": _odds_key(), "regions": "us", "markets": ",".join(markets), "oddsFormat": "american"}, timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _current_wnba_events() -> list[dict[str, Any]]:
    key = _odds_key()
    if not key:
        raise RuntimeError("THE_ODDS_API_KEY is not configured")
    response = requests.get(
        "https://api.the-odds-api.com/v4/sports/basketball_wnba/events",
        params={"apiKey": key}, timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _current_wnba_props(event_id: str, markets: list[str]) -> dict[str, Any]:
    response = requests.get(
        f"https://api.the-odds-api.com/v4/sports/basketball_wnba/events/{event_id}/odds",
        params={"apiKey": _odds_key(), "regions": "us", "markets": ",".join(markets), "oddsFormat": "american"}, timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _current_ncaaf_events() -> list[dict[str, Any]]:
    """Load current NCAAF events for event-level player-prop requests."""
    key = _odds_key()
    if not key:
        raise RuntimeError("THE_ODDS_API_KEY is not configured")
    response = requests.get(
        "https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/events",
        params={"apiKey": key}, timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _current_ncaaf_props(event_id: str, markets: list[str]) -> dict[str, Any]:
    response = requests.get(
        f"https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/events/{event_id}/odds",
        params={"apiKey": _odds_key(), "regions": "us", "markets": ",".join(markets), "oddsFormat": "american"}, timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _current_ncaaf_moneyline_events() -> list[dict[str, Any]]:
    """Load current NCAAF moneylines; individual props remain event-level."""
    key = _odds_key()
    if not key:
        raise RuntimeError("THE_ODDS_API_KEY is not configured")
    response = requests.get(
        "https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds",
        params={"apiKey": key, "regions": "us", "markets": "h2h", "oddsFormat": "american"}, timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _espn_wnba_scoreboard(date: str) -> list[dict[str, Any]]:
    response = requests.get(
        "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
        params={"dates": date.replace("-", ""), "limit": 100}, timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    events = payload.get("events", []) if isinstance(payload, dict) else []
    return [event for event in events if isinstance(event, dict)] if isinstance(events, list) else []


def _espn_wnba_final_game_for_event(date: str, event: dict[str, Any]) -> dict[str, Any] | None:
    away_key, home_key = _name_key(event.get("away_team")), _name_key(event.get("home_team"))
    for candidate in _espn_wnba_scoreboard(date):
        competition = ((candidate.get("competitions") or [{}])[0] if isinstance(candidate.get("competitions"), list) else {})
        competitors = competition.get("competitors", []) if isinstance(competition, dict) else []
        teams = {
            str(item.get("homeAway") or ""): _name_key(((item.get("team") or {}).get("displayName") or ((item.get("team") or {}).get("name"))))
            for item in competitors if isinstance(item, dict)
        }
        status = ((candidate.get("status") or {}).get("type") or {}) if isinstance(candidate.get("status"), dict) else {}
        if teams.get("away") == away_key and teams.get("home") == home_key and status.get("completed") is True:
            return candidate
    return None


def _espn_wnba_box_stats(event_id: Any) -> dict[str, dict[str, float]]:
    response = requests.get(
        "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary",
        params={"event": event_id}, timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    status = ((((payload.get("header") or {}).get("competitions") or [{}])[0].get("status") or {}).get("type") or {}) if isinstance(payload, dict) else {}
    if status.get("completed") is not True:
        return {}
    result: dict[str, dict[str, float]] = {}
    groups = ((payload.get("boxscore") or {}).get("players") or []) if isinstance(payload, dict) else []
    for group in groups if isinstance(groups, list) else []:
        for statistics in group.get("statistics", []) if isinstance(group, dict) else []:
            names = statistics.get("names", []) if isinstance(statistics, dict) else []
            athletes = statistics.get("athletes", []) if isinstance(statistics, dict) else []
            if not isinstance(names, list) or not isinstance(athletes, list):
                continue
            for row in athletes:
                athlete = row.get("athlete", {}) if isinstance(row, dict) else {}
                name = athlete.get("displayName") if isinstance(athlete, dict) else None
                values = row.get("stats", []) if isinstance(row, dict) else []
                if not name or row.get("didNotPlay") is True or not isinstance(values, list):
                    continue
                columns = {str(column): values[index] for index, column in enumerate(names) if index < len(values)}
                points, rebounds, assists = _number(columns.get("PTS")), _number(columns.get("REB")), _number(columns.get("AST"))
                threes_text = str(columns.get("3PT") or "").split("-", 1)[0]
                threes = _number(threes_text)
                if points is None or rebounds is None or assists is None or threes is None:
                    continue
                result[_name_key(name)] = {
                    "points": points, "rebounds": rebounds, "assists": assists, "threes": threes,
                    "points_rebounds_assists": points + rebounds + assists,
                }
    return result


def _espn_ncaaf_scoreboard(date: str) -> list[dict[str, Any]]:
    response = requests.get(
        "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
        params={"dates": date.replace("-", ""), "limit": 500}, timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    events = payload.get("events", []) if isinstance(payload, dict) else []
    return [event for event in events if isinstance(event, dict)] if isinstance(events, list) else []


def _espn_ncaaf_final_game_for_event(date: str, event: dict[str, Any]) -> dict[str, Any] | None:
    away_key, home_key = _name_key(event.get("away_team")), _name_key(event.get("home_team"))
    for candidate in _espn_ncaaf_scoreboard(date):
        competition = ((candidate.get("competitions") or [{}])[0] if isinstance(candidate.get("competitions"), list) else {})
        competitors = competition.get("competitors", []) if isinstance(competition, dict) else []
        teams = {
            str(item.get("homeAway") or ""): _name_key(((item.get("team") or {}).get("displayName") or ((item.get("team") or {}).get("name"))))
            for item in competitors if isinstance(item, dict)
        }
        status = ((candidate.get("status") or {}).get("type") or {}) if isinstance(candidate.get("status"), dict) else {}
        if teams.get("away") == away_key and teams.get("home") == home_key and status.get("completed") is True:
            return candidate
    return None


def _espn_ncaaf_box_stats(event_id: Any) -> dict[str, dict[str, float]]:
    """Normalize only final, observable NCAAF box-score statistics."""
    response = requests.get(
        "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary",
        params={"event": event_id}, timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    status = ((((payload.get("header") or {}).get("competitions") or [{}])[0].get("status") or {}).get("type") or {}) if isinstance(payload, dict) else {}
    if status.get("completed") is not True:
        return {}
    result: dict[str, dict[str, float]] = {}
    groups = ((payload.get("boxscore") or {}).get("players") or []) if isinstance(payload, dict) else []
    category_fields = {
        "passing": {"YDS": "passing_yards", "TD": "passing_touchdowns", "INT": "passing_interceptions"},
        "rushing": {"YDS": "rushing_yards", "TD": "rushing_touchdowns"},
        "receiving": {"REC": "receptions", "YDS": "receiving_yards", "TD": "receiving_touchdowns"},
    }
    for group in groups if isinstance(groups, list) else []:
        for statistics in group.get("statistics", []) if isinstance(group, dict) else []:
            category = str(statistics.get("name") or statistics.get("displayName") or "").lower()
            fields = category_fields.get(category)
            names = statistics.get("names", []) if isinstance(statistics, dict) else []
            athletes = statistics.get("athletes", []) if isinstance(statistics, dict) else []
            if not fields or not isinstance(names, list) or not isinstance(athletes, list):
                continue
            for row in athletes:
                athlete = row.get("athlete", {}) if isinstance(row, dict) else {}
                name = athlete.get("displayName") if isinstance(athlete, dict) else None
                values = row.get("stats", []) if isinstance(row, dict) else []
                if not name or row.get("didNotPlay") is True or not isinstance(values, list):
                    continue
                columns = {str(column).upper(): values[index] for index, column in enumerate(names) if index < len(values)}
                stats = result.setdefault(_name_key(name), {})
                for column, field in fields.items():
                    value = _number(columns.get(column))
                    if value is not None:
                        stats[field] = value
    return result


def _current_mlb_moneyline_events() -> list[dict[str, Any]]:
    """Load the current MLB h2h board for an auditable pregame snapshot."""
    key = _odds_key()
    if not key:
        raise RuntimeError("THE_ODDS_API_KEY is not configured")
    response = requests.get(
        "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds",
        params={"apiKey": key, "regions": "us", "markets": "h2h", "oddsFormat": "american"}, timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _pregame_moneyline_consensus(event: dict[str, Any]) -> dict[str, Any] | None:
    """De-vig every complete h2h book, then use a median fair home probability."""
    home, away = str(event.get("home_team") or ""), str(event.get("away_team") or "")
    books: list[dict[str, Any]] = []
    for bookmaker in event.get("bookmakers", []) if isinstance(event.get("bookmakers"), list) else []:
        if not isinstance(bookmaker, dict):
            continue
        market = next((item for item in bookmaker.get("markets", []) if isinstance(item, dict) and item.get("key") == "h2h"), None)
        outcomes = market.get("outcomes", []) if isinstance(market, dict) and isinstance(market.get("outcomes"), list) else []
        prices = {str(item.get("name") or ""): _number(item.get("price")) for item in outcomes if isinstance(item, dict)}
        if prices.get(home) is not None and prices.get(away) is not None:
            books.append({"bookmaker": bookmaker.get("title") or bookmaker.get("key") or "Sportsbook", "over": prices[home], "under": prices[away]})
    if len(books) < 2:
        return None
    representative = _representative_market_consensus(books)
    if representative is None:
        return None
    home_odds, away_odds, fair_home, reference_bookmaker = representative
    return {
        "fair_home_win_probability": round(fair_home * 100, 2), "fair_away_win_probability": round((1 - fair_home) * 100, 2),
        "home_moneyline": home_odds, "away_moneyline": away_odds, "book_count": len(books),
        "bookmakers": [str(book["bookmaker"]) for book in books], "reference_bookmaker": reference_bookmaker,
        "consensus_method": "median_devig_per_book_v2",
    }


def _has_started(commence_time: Any) -> bool:
    return _has_started_at(commence_time, datetime.now(timezone.utc))


def _has_started_at(commence_time: Any, reference_time: datetime) -> bool:
    try:
        value = datetime.fromisoformat(str(commence_time).replace("Z", "+00:00"))
        return value <= reference_time
    except ValueError:
        return True


def _current_nfl_preseason_odds() -> list[dict[str, Any]]:
    """Load only featured preseason game markets, never pretend props exist."""
    key = _odds_key()
    if not key:
        raise RuntimeError("THE_ODDS_API_KEY is not configured")
    response = requests.get(
        "https://api.the-odds-api.com/v4/sports/americanfootball_nfl_preseason/odds",
        params={"apiKey": key, "regions": "us", "markets": ",".join(sorted(NFL_PRESEASON_GAME_MARKETS)), "oddsFormat": "american"},
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _historical_nfl_preseason_events(snapshot: str) -> list[dict[str, Any]]:
    response = requests.get(
        "https://api.the-odds-api.com/v4/historical/sports/americanfootball_nfl_preseason/events",
        params={"apiKey": _odds_key(), "date": snapshot}, timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", payload) if isinstance(payload, dict) else []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _historical_nfl_preseason_odds(event_id: str, snapshot: str) -> dict[str, Any]:
    response = requests.get(
        f"https://api.the-odds-api.com/v4/historical/sports/americanfootball_nfl_preseason/events/{event_id}/odds",
        params={"apiKey": _odds_key(), "date": snapshot, "regions": "us", "markets": ",".join(sorted(NFL_PRESEASON_GAME_MARKETS)), "oddsFormat": "american"}, timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    return data if isinstance(data, dict) else {}


def _valid_nfl_preseason_snapshot_event(event: dict[str, Any], snapshot: str) -> bool:
    """Accept a true pregame observation, not a schedule posted days early."""
    try:
        captured = datetime.fromisoformat(snapshot.replace("Z", "+00:00"))
        commence = datetime.fromisoformat(str(event.get("commence_time") or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    lead_hours = (commence - captured).total_seconds() / 3600
    return 0 <= lead_hours <= NFL_PRESEASON_MAX_SNAPSHOT_LEAD_HOURS


def _nfl_team_name(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get("full_name") or value.get("display_name") or value.get("name") or value.get("abbreviation") or "")


def _nfl_final_game_for_event(date: str, event: dict[str, Any]) -> dict[str, Any] | None:
    """Return a provider-confirmed NFL final only; never infer a score."""
    key = os.getenv("BALLDONTLIE_API_KEY")
    away_key, home_key = _name_key(event.get("away_team")), _name_key(event.get("home_team"))
    if key:
        try:
            response = requests.get(
                "https://api.balldontlie.io/nfl/v1/games", headers={"Authorization": key, "Accept": "application/json"},
                params={"dates[]": date, "per_page": 100}, timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            games = payload.get("data", []) if isinstance(payload, dict) else []
            for game in games if isinstance(games, list) else []:
                if not isinstance(game, dict):
                    continue
                away = _name_key(_nfl_team_name(game.get("visitor_team") or game.get("away_team")))
                home = _name_key(_nfl_team_name(game.get("home_team")))
                home_score = _number(game.get("home_score", game.get("home_team_score")))
                away_score = _number(game.get("visitor_score", game.get("away_score", game.get("visitor_team_score"))))
                status = str(game.get("status") or "").lower()
                if away == away_key and home == home_key and away_score is not None and home_score is not None and "final" in status:
                    return {"home_score": home_score, "away_score": away_score, "status": game.get("status"), "game_id": game.get("id"), "provider": "BallDontLie"}
        except requests.RequestException:
            # Preseason coverage can be missing from a provider plan. ESPN's
            # completed public scoreboard is used only as a final-score
            # verification fallback, never for odds or player projections.
            pass
    try:
        # The Odds API timestamps are UTC while ESPN's scoreboard is keyed to
        # the local game date. Check adjacent dates so a Thursday-night game
        # that starts after midnight UTC is never left permanently ungraded.
        base_date = datetime.fromisoformat(date).date()
        score_dates = {(base_date + timedelta(days=offset)).strftime("%Y%m%d") for offset in (-1, 0, 1)}
        for score_date in sorted(score_dates):
            response = requests.get(
                "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
                params={"dates": score_date, "limit": 100}, timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            events = payload.get("events", []) if isinstance(payload, dict) else []
            for game in events if isinstance(events, list) else []:
                if not isinstance(game, dict) or not bool(((game.get("status") or {}).get("type") or {}).get("completed")):
                    continue
                competition = (game.get("competitions") or [{}])[0]
                competitors = competition.get("competitors", []) if isinstance(competition, dict) else []
                teams = {str(item.get("homeAway") or "").lower(): item for item in competitors if isinstance(item, dict)}
                away, home = teams.get("away", {}), teams.get("home", {})
                away_name = _name_key(((away.get("team") or {}).get("displayName")))
                home_name = _name_key(((home.get("team") or {}).get("displayName")))
                away_score, home_score = _number(away.get("score")), _number(home.get("score"))
                if away_name == away_key and home_name == home_key and away_score is not None and home_score is not None:
                    return {"home_score": home_score, "away_score": away_score, "status": ((game.get("status") or {}).get("type") or {}).get("name"), "game_id": game.get("id"), "provider": "ESPN public completed scoreboard"}
    except requests.RequestException:
        return None
    return None


def _nfl_projection_snapshot_rows() -> list[dict[str, Any]]:
    """Fetch the configured Tank01 weekly projection feed for forward auditing.

    The rows are preserved as observations only.  A preseason projection is
    not blended into a regular-season model or converted to a betting pick.
    """
    key = os.getenv("RAPIDAPI_KEY_TANK01") or os.getenv("RAPIDAPI_KEY")
    if not key:
        raise RuntimeError("RAPIDAPI_KEY_TANK01 is not configured")
    host = "tank01-nfl-live-in-game-real-time-statistics-nfl.p.rapidapi.com"
    params = {
        "week": os.getenv("TANK01_NFL_PROJECTION_WEEK", "1"), "archiveSeason": os.getenv("TANK01_NFL_PROJECTION_SEASON", str(datetime.now().year)), "itemFormat": "list",
        "twoPointConversions": 2, "passYards": ".04", "passAttempts": "-.5", "passTD": 4, "passCompletions": 1, "passInterceptions": -2,
        "pointsPerReception": 1, "carries": ".2", "rushYards": ".1", "rushTD": 6, "fumbles": -2, "receivingYards": ".1", "receivingTD": 6,
        "targets": ".1", "fgMade": 3, "fgMissed": -1, "xpMade": 1, "xpMissed": -1,
    }
    response = requests.get(f"https://{host}/getNFLProjections", headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": host, "Accept": "application/json"}, params=params, timeout=45)
    response.raise_for_status()
    payload = response.json()
    body = payload.get("body", payload) if isinstance(payload, dict) else {}
    raw = body.get("playerProjections", body) if isinstance(body, dict) else []
    rows = list(raw.values()) if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("longName"):
            continue
        passing = row.get("Passing") if isinstance(row.get("Passing"), dict) else {}
        rushing = row.get("Rushing") if isinstance(row.get("Rushing"), dict) else {}
        receiving = row.get("Receiving") if isinstance(row.get("Receiving"), dict) else {}
        result.append({
            "player": row.get("longName"), "player_key": _name_key(row.get("longName")),
            "team": row.get("team") or row.get("teamAbv") or row.get("teamAbbreviation"), "position": row.get("pos") or row.get("position"),
            "passing_yards": _number(passing.get("passYds")), "passing_touchdowns": _number(passing.get("passTD")),
            "rushing_yards": _number(rushing.get("rushYds")), "receiving_yards": _number(receiving.get("recYds")), "receptions": _number(receiving.get("receptions")),
        })
    return result


def _compact_preseason_books(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep auditable posted game prices while avoiding provider payload bloat."""
    compact: list[dict[str, Any]] = []
    for bookmaker in event.get("bookmakers", []) if isinstance(event, dict) else []:
        if not isinstance(bookmaker, dict):
            continue
        markets: list[dict[str, Any]] = []
        for market in bookmaker.get("markets", []):
            if not isinstance(market, dict) or market.get("key") not in NFL_PRESEASON_GAME_MARKETS:
                continue
            outcomes = []
            for outcome in market.get("outcomes", []):
                if isinstance(outcome, dict):
                    outcomes.append({"name": outcome.get("name"), "point": _number(outcome.get("point")), "price": _number(outcome.get("price"))})
            if outcomes:
                markets.append({"key": market.get("key"), "outcomes": outcomes})
        if markets:
            compact.append({"bookmaker": bookmaker.get("title") or bookmaker.get("key"), "markets": markets})
    return compact


def _mlb_stats_api(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(f"https://statsapi.mlb.com/api/v1/{path.lstrip('/')}", params=params or {}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _mlb_schedule(date: str) -> list[dict[str, Any]]:
    payload = _mlb_stats_api("schedule", {"sportId": 1, "date": date, "hydrate": "probablePitcher,venue"})
    dates = payload.get("dates", []) if isinstance(payload.get("dates"), list) else []
    games: list[dict[str, Any]] = []
    for day in dates:
        if isinstance(day, dict):
            games.extend(item for item in day.get("games", []) if isinstance(item, dict))
    return games


def _mlb_lineup(game_pk: Any) -> tuple[dict[str, list[dict[str, Any]]], str]:
    """Return announced batting orders where MLB has published them.

    A pregame roster is not represented as a confirmed lineup unless it has a
    positive batting order. This avoids treating a placeholder roster as fact.
    """
    payload = _mlb_stats_api(f"game/{game_pk}/boxscore")
    teams = payload.get("teams", {}) if isinstance(payload.get("teams"), dict) else {}
    lineups: dict[str, list[dict[str, Any]]] = {"away": [], "home": []}
    for side in ("away", "home"):
        team = teams.get(side, {}) if isinstance(teams.get(side), dict) else {}
        players = team.get("players", {}) if isinstance(team.get("players"), dict) else {}
        for player in players.values():
            if not isinstance(player, dict):
                continue
            order = _number(player.get("battingOrder"))
            person = player.get("person", {}) if isinstance(player.get("person"), dict) else {}
            if order and order > 0 and person.get("fullName"):
                lineups[side].append({"player_id": person.get("id"), "name": person.get("fullName"), "batting_order": int(order)})
        lineups[side].sort(key=lambda player: player["batting_order"])
    return lineups, "announced" if any(lineups.values()) else "unavailable"


def _mlb_pitcher_context(probable: Any) -> dict[str, Any] | None:
    if not isinstance(probable, dict) or not probable.get("id"):
        return None
    context = {"player_id": probable.get("id"), "name": probable.get("fullName")}
    try:
        person = _mlb_stats_api(f"people/{probable['id']}")
        details = person.get("people", [{}])
        details = details[0] if isinstance(details, list) and details and isinstance(details[0], dict) else {}
        hand = details.get("pitchHand", {}) if isinstance(details.get("pitchHand"), dict) else {}
        context["throws"] = hand.get("code")
    except requests.RequestException:
        context["throws"] = None
    return context


def _multi_book_prop_consensus(odds: dict[str, Any], markets: list[str]) -> tuple[dict[tuple[str, str, float], list[dict[str, Any]]], int]:
    """Return complete over/under price pairs grouped across bookmakers."""
    consensus: dict[tuple[str, str, float], list[dict[str, Any]]] = defaultdict(list)
    for bookmaker in odds.get("bookmakers", []) if isinstance(odds, dict) else []:
        if not isinstance(bookmaker, dict):
            continue
        book_name = str(bookmaker.get("title") or bookmaker.get("key") or "Sportsbook")
        for market in bookmaker.get("markets", []):
            if not isinstance(market, dict):
                continue
            market_key = str(market.get("key") or "")
            if market_key not in markets:
                continue
            paired: dict[tuple[str, float], dict[str, float | None]] = {}
            for outcome in market.get("outcomes", []):
                if not isinstance(outcome, dict):
                    continue
                side = str(outcome.get("name") or "").lower()
                player = str(outcome.get("description") or outcome.get("player") or "").strip()
                line = _number(outcome.get("point"))
                if player and line is not None and side in {"over", "under"}:
                    paired.setdefault((player, line), {"over": None, "under": None})[side] = _number(outcome.get("price"))
            for (player, line), prices in paired.items():
                if prices.get("over") is not None and prices.get("under") is not None:
                    consensus[(market_key, player, line)].append({"bookmaker": book_name, "over": prices["over"], "under": prices["under"]})
    return consensus, sum(1 for books in consensus.values() if len(books) < 2)


def _representative_market_consensus(books: list[dict[str, Any]]) -> tuple[float, float, float, str] | None:
    """De-vig each book before finding a consensus; never median American odds.

    American odds are not linear around even money: a raw median can turn
    valid -130 and +128 prices into an impossible -1.  We instead take the
    median no-vig probability, then retain the complete price pair from the
    actual book closest to that probability for transparent payout auditing.
    """
    normalized: list[tuple[float, dict[str, Any]]] = []
    for book in books:
        fair_over = _fair_over_probability(book.get("over"), book.get("under"))
        if fair_over is not None:
            normalized.append((fair_over, book))
    if len(normalized) < 2:
        return None
    consensus_probability = float(median([fair for fair, _ in normalized]))
    _, reference = min(normalized, key=lambda item: abs(item[0] - consensus_probability))
    over, under = _number(reference.get("over")), _number(reference.get("under"))
    if over is None or under is None:
        return None
    return over, under, consensus_probability, str(reference.get("bookmaker") or "Sportsbook")


def _backtest_store(record: dict[str, Any]) -> None:
    store = _store()
    if store:
        store.collection("prediction_backtest_ledger").document(record["id"]).set(record, merge=True)
    else:
        _memory_backtests[record["id"]] = record


@prediction_ledger_bp.get("/market-consensus/mlb")
def latest_mlb_market_consensus():
    """Return the newest saved MLB multi-book pregame board for the app.

    This is intentionally an observational endpoint.  It exposes the stored
    market and the provider projection captured beside it, but does not select
    a side, calculate a model edge, or make a wagering recommendation.
    """
    try:
        limit = min(300, max(1, int(request.args.get("limit") or 150)))
    except ValueError:
        limit = 150

    store = _store()
    if store:
        rows = [snapshot.to_dict() or {} for snapshot in store.collection("prediction_market_snapshots")
                .where("record_type", "==", "pregame_market_consensus").limit(5000).stream()]
    else:
        rows = [row for row in _memory_backtests.values() if row.get("record_type") == "pregame_market_consensus"]

    rows = [row for row in rows if row.get("sport") == "mlb" and row.get("taken_at")]
    if not rows:
        return jsonify({"success": True, "data": [], "message": "No saved MLB pregame market consensus is available yet."})

    # Every run uses one exact timestamp, making this a coherent board rather
    # than an accidental mixture of lines taken at different points in the day.
    taken_at = max(str(row.get("taken_at")) for row in rows)
    latest = [row for row in rows if str(row.get("taken_at")) == taken_at]
    latest.sort(key=lambda row: (str(row.get("commence_time") or ""), str(row.get("market") or ""), str(row.get("player") or "")))

    def public_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"), "player": row.get("player"), "market": row.get("market"),
            "market_key": row.get("market_key"), "line": row.get("line"),
            "projection": row.get("projection"), "projection_sample_games": row.get("projection_sample_games"),
            "game": row.get("game"), "commence_time": row.get("commence_time"),
            "over_odds": row.get("over_odds"), "under_odds": row.get("under_odds"),
            "fair_probability_over": row.get("fair_probability_over"), "book_count": row.get("book_count"),
            "bookmakers": row.get("bookmakers", []), "reference_bookmaker": row.get("reference_bookmaker"),
            "projection_source": row.get("projection_source"), "taken_at": row.get("taken_at"),
            "consensus_method": row.get("consensus_method"),
        }

    return jsonify({
        "success": True,
        "research_only": True,
        "data": [public_row(row) for row in latest[:limit]],
        "taken_at": taken_at,
        "total": len(latest),
        "message": "Saved multi-book pregame market consensus. It is not a model edge or wagering recommendation.",
    })


@prediction_ledger_bp.post("/snapshots/mlb/market-consensus")
def snapshot_mlb_market_consensus():
    """Persist a real multi-book MLB prop snapshot for future forward testing.

    These rows are observational data, not predictions.  They make it possible
    to distinguish a player-model signal from a one-book pricing artifact once
    enough future games have settled.
    """
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    requested = [value.strip() for value in str(request.args.get("markets") or "batter_hits").split(",") if value.strip()]
    markets = [market for market in requested if market in MLB_BACKTEST_MARKETS]
    if not markets:
        return jsonify({"error": "Provide one or more supported MLB markets."}), 400
    try:
        max_events = min(12, max(1, int(request.args.get("max_events") or 3)))
    except ValueError:
        max_events = 3
    taken_at = _now()
    try:
        events = _current_mlb_events()[:max_events]
    except requests.RequestException as error:
        return jsonify({"error": f"Current MLB event lookup failed ({error.response.status_code if error.response else 'request error'})."}), 502
    stored = skipped = 0
    errors: list[str] = []
    store = _store()
    # Capture the projection available at snapshot time beside every posted
    # market.  Future grading can then measure forecasting accuracy without
    # reconstructing a changed season-average after the game has finished.
    try:
        player_projections = _mlb_projections()
    except Exception:
        player_projections = {}
    for event in events:
        event_id = str(event.get("id") or "")
        if not event_id:
            continue
        try:
            odds = _current_mlb_props(event_id, markets)
        except requests.RequestException as error:
            errors.append(f"{event_id}: {error.response.status_code if error.response else 'request error'}")
            continue
        consensus, incomplete_pairs = _multi_book_prop_consensus(odds, markets)
        skipped += incomplete_pairs
        for (market_key, player, line), books in consensus.items():
            # A two-book minimum avoids treating a solitary/possibly stale book
            # as a market consensus.  Preserve the raw book count for audits.
            if len(books) < 2:
                skipped += 1
                continue
            representative = _representative_market_consensus(books)
            if representative is None:
                skipped += 1
                continue
            over, under, fair_over, reference_bookmaker = representative
            player_projection = player_projections.get(_name_key(player), {})
            record = {
                "id": hashlib.sha256(f"mlb-market-snapshot|{taken_at}|{event_id}|{market_key}|{player}|{line}".encode()).hexdigest()[:32],
                "sport": "mlb", "record_type": "pregame_market_consensus", "taken_at": taken_at,
                "event_id": event_id, "game": f"{event.get('away_team')} @ {event.get('home_team')}", "commence_time": event.get("commence_time"),
                "game_date": str(event.get("commence_time") or "")[:10], "player": player, "market_key": market_key,
                "market": MLB_BACKTEST_MARKETS[market_key][0], "line": line, "over_odds": over, "under_odds": under,
                "projection": _number(player_projection.get(market_key)), "projection_sample_games": _number(player_projection.get("_sample_games")),
                "fair_probability_over": round(fair_over * 100, 2), "book_count": len(books),
                "bookmakers": [book["bookmaker"] for book in books], "reference_bookmaker": reference_bookmaker,
                "consensus_method": "median_devig_per_book_v2", "projection_source": "BallDontLie MLB season-context projection at snapshot time" if player_projection else None,
                "source": "The Odds API current multi-book player-prop snapshot",
            }
            if store:
                store.collection("prediction_market_snapshots").document(record["id"]).set(record)
            else:
                _memory_backtests[record["id"]] = record
            stored += 1
    return jsonify({"success": True, "isolated": True, "record_type": "pregame_market_consensus", "taken_at": taken_at, "events_checked": len(events), "markets": markets, "stored": stored, "skipped": skipped, "errors": errors[:10], "message": "Stored real multi-book pregame market observations. No prediction or live-model change was made."})


@prediction_ledger_bp.post("/snapshots/wnba/market-consensus")
def snapshot_wnba_market_consensus():
    """Persist a research-only WNBA player-prop market snapshot before games."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    requested = [value.strip() for value in str(request.args.get("markets") or "player_points,player_rebounds,player_assists,player_threes,player_points_rebounds_assists").split(",") if value.strip()]
    markets = [market for market in requested if market in WNBA_MARKETS]
    if not markets:
        return jsonify({"error": "Provide one or more supported WNBA player-prop markets."}), 400
    try:
        max_events = min(12, max(1, int(request.args.get("max_events") or 6)))
    except ValueError:
        max_events = 6
    taken_at = _now()
    try:
        events = [event for event in _current_wnba_events() if not _has_started(event.get("commence_time"))][:max_events]
    except (requests.RequestException, RuntimeError) as error:
        return jsonify({"error": f"Current WNBA event lookup failed ({error.response.status_code if isinstance(error, requests.RequestException) and error.response else str(error)})."}), 502
    stored = skipped = 0
    errors: list[str] = []
    store = _store()
    for event in events:
        event_id = str(event.get("id") or "")
        if not event_id:
            skipped += 1
            continue
        try:
            odds = _current_wnba_props(event_id, markets)
        except requests.RequestException as error:
            errors.append(f"{event_id}: {error.response.status_code if error.response else 'request error'}")
            continue
        consensus, incomplete_pairs = _multi_book_prop_consensus(odds, markets)
        skipped += incomplete_pairs
        for (market_key, player, line), books in consensus.items():
            if len(books) < 2:
                skipped += 1
                continue
            representative = _representative_market_consensus(books)
            if representative is None:
                skipped += 1
                continue
            over, under, fair_over, reference_bookmaker = representative
            record = {
                "id": hashlib.sha256(f"wnba-market-snapshot|{taken_at}|{event_id}|{market_key}|{player}|{line}".encode()).hexdigest()[:32],
                "sport": "wnba", "record_type": "pregame_wnba_market_consensus", "isolation": "wnba_research",
                "eligible_for_live_calibration": False, "taken_at": taken_at, "event_id": event_id,
                "game": f"{event.get('away_team')} @ {event.get('home_team')}", "commence_time": event.get("commence_time"),
                "game_date": _eastern_sports_date(event.get("commence_time")), "player": player, "market_key": market_key,
                "market": WNBA_MARKETS[market_key][0], "line": line, "over_odds": over, "under_odds": under,
                "fair_probability_over": round(fair_over * 100, 2), "book_count": len(books),
                "bookmakers": [book["bookmaker"] for book in books], "reference_bookmaker": reference_bookmaker,
                "consensus_method": "median_devig_per_book_v2", "projection": None,
                "projection_source": None, "source": "The Odds API current multi-book WNBA player-prop snapshot",
            }
            if store:
                store.collection("prediction_market_snapshots").document(record["id"]).set(record)
            else:
                _memory_backtests[record["id"]] = record
            stored += 1
    return jsonify({"success": True, "isolated": True, "record_type": "pregame_wnba_market_consensus", "season_phase": "regular_season", "taken_at": taken_at, "events_checked": len(events), "markets": markets, "stored": stored, "skipped": skipped, "errors": errors[:10], "message": "Stored real multi-book WNBA pregame market observations. No player projection, recommendation, or live-model change was made."})


@prediction_ledger_bp.post("/snapshots/ncaaf/market-consensus")
def snapshot_ncaaf_market_consensus():
    """Persist current NCAAF player-prop observations for later research grading."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    requested = [value.strip() for value in str(request.args.get("markets") or ",".join(NCAAF_PROP_MARKETS)).split(",") if value.strip()]
    markets = [market for market in requested if market in NCAAF_PROP_MARKETS]
    if not markets:
        return jsonify({"error": "Provide one or more supported NCAAF player-prop markets."}), 400
    try:
        max_events = min(12, max(1, int(request.args.get("max_events") or 6)))
    except ValueError:
        max_events = 6
    taken_at = _now()
    try:
        events = [event for event in _current_ncaaf_events() if not _has_started(event.get("commence_time"))][:max_events]
    except (requests.RequestException, RuntimeError) as error:
        detail = error.response.status_code if isinstance(error, requests.RequestException) and error.response else str(error)
        return jsonify({"error": f"Current NCAAF event lookup failed ({detail})."}), 502
    stored = skipped = 0
    errors: list[str] = []
    store = _store()
    for event in events:
        event_id = str(event.get("id") or "")
        if not event_id:
            skipped += 1
            continue
        try:
            odds = _current_ncaaf_props(event_id, markets)
        except requests.RequestException as error:
            errors.append(f"{event_id}: {error.response.status_code if error.response else 'request error'}")
            continue
        consensus, incomplete_pairs = _multi_book_prop_consensus(odds, markets)
        skipped += incomplete_pairs
        for (market_key, player, line), books in consensus.items():
            if len(books) < 2:
                skipped += 1
                continue
            representative = _representative_market_consensus(books)
            if representative is None:
                skipped += 1
                continue
            over, under, fair_over, reference_bookmaker = representative
            record = {
                "id": hashlib.sha256(f"ncaaf-market-snapshot|{taken_at}|{event_id}|{market_key}|{player}|{line}".encode()).hexdigest()[:32],
                "sport": "ncaaf", "record_type": "pregame_ncaaf_market_consensus", "isolation": "ncaaf_research",
                "eligible_for_live_calibration": False, "taken_at": taken_at, "event_id": event_id,
                "game": f"{event.get('away_team')} @ {event.get('home_team')}", "commence_time": event.get("commence_time"),
                "game_date": _eastern_sports_date(event.get("commence_time")), "player": player, "market_key": market_key,
                "market": NCAAF_PROP_MARKETS[market_key][0], "line": line, "over_odds": over, "under_odds": under,
                "fair_probability_over": round(fair_over * 100, 2), "book_count": len(books),
                "bookmakers": [book["bookmaker"] for book in books], "reference_bookmaker": reference_bookmaker,
                "consensus_method": "median_devig_per_book_v2", "projection": None, "projection_source": None,
                "source": "The Odds API current multi-book NCAAF player-prop snapshot",
            }
            if store:
                store.collection("prediction_market_snapshots").document(record["id"]).set(record)
            else:
                _memory_backtests[record["id"]] = record
            stored += 1
    return jsonify({"success": True, "isolated": True, "record_type": "pregame_ncaaf_market_consensus", "taken_at": taken_at, "events_checked": len(events), "markets": markets, "stored": stored, "skipped": skipped, "errors": errors[:10], "message": "Stored real multi-book NCAAF pregame player-prop observations. No prediction, recommendation, or live-model change was made."})


@prediction_ledger_bp.post("/snapshots/ncaaf/moneyline-context")
def snapshot_ncaaf_moneyline_context():
    """Persist auditable NCAAF pregame moneylines before kickoff."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    try:
        max_events = min(20, max(1, int(request.args.get("max_events") or 12)))
    except ValueError:
        max_events = 12
    try:
        events = [event for event in _current_ncaaf_moneyline_events() if not _has_started(event.get("commence_time"))][:max_events]
    except (requests.RequestException, RuntimeError) as error:
        detail = error.response.status_code if isinstance(error, requests.RequestException) and error.response else str(error)
        return jsonify({"error": f"Current NCAAF moneyline lookup failed ({detail})."}), 502
    taken_at, stored, skipped = _now(), 0, 0
    store = _store()
    for event in events:
        event_id, commence_time = str(event.get("id") or ""), str(event.get("commence_time") or "")
        consensus = _pregame_moneyline_consensus(event) if event_id else None
        if not event_id or consensus is None:
            skipped += 1
            continue
        record = {
            "id": hashlib.sha256(f"ncaaf-moneyline-context|{taken_at}|{event_id}".encode()).hexdigest()[:32],
            "sport": "ncaaf", "record_type": "pregame_ncaaf_moneyline_context", "isolation": "forward_moneyline_research",
            "eligible_for_live_calibration": False, "taken_at": taken_at, "event_id": event_id,
            "game": f"{event.get('away_team')} @ {event.get('home_team')}", "game_date": _eastern_sports_date(commence_time), "commence_time": commence_time,
            "market": consensus, "context_status": "market_only", "source": "The Odds API current multi-book NCAAF moneyline snapshot",
        }
        if store:
            store.collection("prediction_ncaaf_moneyline_context_snapshots").document(record["id"]).set(record)
        else:
            _memory_backtests[record["id"]] = record
        stored += 1
    return jsonify({"success": True, "isolated": True, "record_type": "pregame_ncaaf_moneyline_context", "taken_at": taken_at, "events_checked": len(events), "stored": stored, "skipped": skipped, "message": "Stored pregame multi-book NCAAF moneylines. These research records cannot change live recommendations."})


@prediction_ledger_bp.post("/snapshots/nfl/preseason")
def snapshot_nfl_preseason():
    """Persist current preseason projections and game markets for later grading.

    NFL preseason player-prop pricing is not assumed to exist.  Tank01 player
    projections and The Odds API featured game markets are stored separately
    with an explicit preseason phase so they cannot alter regular-season
    picks, subscription access, or model calibration.
    """
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    try:
        max_events = min(20, max(1, int(request.args.get("max_events") or 20)))
    except ValueError:
        max_events = 20
    taken_at = _now()
    try:
        events = _current_nfl_preseason_odds()[:max_events]
        projections = _nfl_projection_snapshot_rows()
    except requests.RequestException as error:
        return jsonify({"error": f"NFL preseason source request failed ({error.response.status_code if error.response else 'request error'})."}), 502
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 503

    store = _store()
    market_stored = projection_stored = skipped = 0
    for event in events:
        event_id = str(event.get("id") or "")
        commence_time = str(event.get("commence_time") or "")
        books = _compact_preseason_books(event)
        if not event_id or not books:
            skipped += 1
            continue
        record = {
            "id": hashlib.sha256(f"nfl-preseason-market|{taken_at}|{event_id}".encode()).hexdigest()[:32],
            "sport": "nfl", "season_phase": "preseason", "record_type": "pregame_game_market_snapshot", "isolation": "nfl_preseason_research",
            "eligible_for_live_calibration": False, "taken_at": taken_at, "event_id": event_id,
            "game": f"{event.get('away_team')} @ {event.get('home_team')}", "game_date": commence_time[:10], "commence_time": commence_time,
            "markets": ["h2h", "spreads", "totals"], "book_count": len(books), "bookmakers": books,
            "source": "The Odds API current multi-book NFL preseason featured-market snapshot",
        }
        if store:
            store.collection("prediction_nfl_preseason_snapshots").document(record["id"]).set(record)
        else:
            _memory_backtests[record["id"]] = record
        market_stored += 1

    season = os.getenv("TANK01_NFL_PROJECTION_SEASON", str(datetime.now().year))
    week = os.getenv("TANK01_NFL_PROJECTION_WEEK", "1")
    for player in projections:
        if not player.get("player_key"):
            skipped += 1
            continue
        record = {
            "id": hashlib.sha256(f"nfl-preseason-projection|{taken_at}|{player['player_key']}".encode()).hexdigest()[:32],
            "sport": "nfl", "season_phase": "preseason", "record_type": "pregame_player_projection_snapshot", "isolation": "nfl_preseason_research",
            "eligible_for_live_calibration": False, "taken_at": taken_at, "season": season, "week": week,
            **player, "source": "Tank01 configured NFL weekly projection feed",
        }
        if store:
            store.collection("prediction_nfl_preseason_snapshots").document(record["id"]).set(record)
        else:
            _memory_backtests[record["id"]] = record
        projection_stored += 1
    return jsonify({"success": True, "isolated": True, "season_phase": "preseason", "eligible_for_live_calibration": False, "taken_at": taken_at, "events_checked": len(events), "market_snapshots": market_stored, "player_projection_snapshots": projection_stored, "skipped": skipped, "message": "Stored NFL preseason featured game markets and Tank01 player projections separately. No live picks or regular-season model changed."})


@prediction_ledger_bp.post("/snapshots/nfl/preseason/historical-markets")
def snapshot_historical_nfl_preseason_markets():
    """Backfill point-in-time preseason featured markets, preview first.

    This is intentionally a team-market research dataset.  It is not a
    player-prop model, cannot alter live output, and never treats an
    unverified score as settled.
    """
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    date = str(request.args.get("date") or "")
    snapshot = str(request.args.get("snapshot") or f"{date}T13:00:00Z")
    try:
        max_events = min(3, max(1, int(request.args.get("max_events") or 3)))
        offset = max(0, int(request.args.get("offset") or 0))
    except ValueError:
        max_events, offset = 3, 0
    commit = str(request.args.get("commit") or "").lower() == "true"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not snapshot.startswith(f"{date}T"):
        return jsonify({"error": "Provide date=YYYY-MM-DD and a same-day pregame snapshot."}), 400
    if date >= datetime.now(timezone.utc).date().isoformat():
        return jsonify({"error": "Historical preseason imports require a completed past date."}), 400
    try:
        events = _historical_nfl_preseason_events(snapshot)
    except requests.RequestException as error:
        return jsonify({"error": f"Historical NFL preseason event lookup failed ({error.response.status_code if error.response else 'request error'})."}), 502
    # The historical event list is a point-in-time schedule, so it can include
    # games many days ahead of the requested snapshot. Keep only games that
    # begin within a true pregame window after the snapshot.
    future_events_skipped = sum(1 for item in events if not _valid_nfl_preseason_snapshot_event(item, snapshot))
    eligible_events = [item for item in events if _valid_nfl_preseason_snapshot_event(item, snapshot)]
    events = eligible_events[offset:offset + max_events]
    preview = [{"event_id": item.get("id"), "game": f"{item.get('away_team')} @ {item.get('home_team')}", "commence_time": item.get("commence_time")} for item in events]
    if not commit:
        return jsonify({"success": True, "preview": True, "isolated": True, "date": date, "snapshot": snapshot, "offset": offset, "eligible_event_count": len(eligible_events), "next_offset": offset + len(events) if offset + len(events) < len(eligible_events) else None, "events": preview, "future_events_skipped": future_events_skipped, "estimated_historical_credits": len(events) * 30, "message": "Review the historical preseason games and cost estimate, then rerun with commit=true. This imports featured game markets only."})
    store = _store()
    stored = final_scores_verified = skipped = 0
    errors: list[str] = []
    for event in events:
        event_id = str(event.get("id") or "")
        if not event_id:
            skipped += 1
            continue
        try:
            odds = _historical_nfl_preseason_odds(event_id, snapshot)
            books = _compact_preseason_books(odds)
            final = _nfl_final_game_for_event(date, event)
        except requests.RequestException as error:
            errors.append(f"{event_id}: {error.response.status_code if error.response else 'request error'}")
            continue
        if not books:
            skipped += 1
            continue
        record = {
            "id": hashlib.sha256(f"nfl-preseason-historical-market|{snapshot}|{event_id}".encode()).hexdigest()[:32],
            "sport": "nfl", "season_phase": "preseason", "record_type": "historical_pregame_game_market_snapshot", "isolation": "nfl_preseason_historical_research",
            "eligible_for_live_calibration": False, "snapshot": snapshot, "taken_at": snapshot, "event_id": event_id,
            "game": f"{event.get('away_team')} @ {event.get('home_team')}", "game_date": date, "commence_time": event.get("commence_time"),
            "markets": ["h2h", "spreads", "totals"], "book_count": len(books), "bookmakers": books,
            "final_score": final, "settled_at": _now() if final else None,
            "result_source": str(final.get("provider") or "verified NFL final-score provider") if final else None,
            "source": "The Odds API historical multi-book NFL preseason featured-market snapshot",
        }
        if store:
            store.collection("prediction_nfl_preseason_snapshots").document(record["id"]).set(record, merge=True)
        else:
            _memory_backtests[record["id"]] = record
        stored += 1
        final_scores_verified += int(final is not None)
    return jsonify({"success": True, "preview": False, "isolated": True, "date": date, "snapshot": snapshot, "offset": offset, "eligible_event_count": len(eligible_events), "next_offset": offset + len(events) if offset + len(events) < len(eligible_events) else None, "events_checked": len(events), "future_events_skipped": future_events_skipped, "stored": stored, "final_scores_verified": final_scores_verified, "skipped": skipped, "errors": errors[:10], "message": "Stored historical NFL preseason featured markets. Only provider-confirmed final scores were attached; no live model changed."})


@prediction_ledger_bp.post("/snapshots/mlb/pregame-context")
def snapshot_mlb_pregame_context():
    """Store timestamped MLB lineup, pitcher, venue, and weather context.

    This is a forward-looking observation pipeline. It deliberately records
    unavailable lineups as unavailable rather than inferring a starting order.
    """
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    requested_date = str(request.args.get("date") or "")
    if requested_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", requested_date):
        return jsonify({"error": "date must use YYYY-MM-DD."}), 400
    try:
        max_events = min(15, max(1, int(request.args.get("max_events") or 15)))
    except ValueError:
        max_events = 15
    try:
        events = _current_mlb_events()
    except requests.RequestException as error:
        return jsonify({"error": f"Current MLB event lookup failed ({error.response.status_code if error.response else 'request error'})."}), 502
    if requested_date:
        events = [event for event in events if str(event.get("commence_time") or "")[:10] == requested_date]
    events = events[:max_events]
    taken_at = _now()
    schedules: dict[str, list[dict[str, Any]]] = {}
    stored = skipped = 0
    errors: list[str] = []
    store = _store()
    for event in events:
        event_id = str(event.get("id") or "")
        date = str(event.get("commence_time") or "")[:10]
        if not event_id or not date:
            skipped += 1
            continue
        try:
            if date not in schedules:
                schedules[date] = _mlb_schedule(date)
        except requests.RequestException as error:
            errors.append(f"{event_id}: schedule {error.response.status_code if error.response else 'request error'}")
            continue
        away_key, home_key = _name_key(event.get("away_team")), _name_key(event.get("home_team"))
        game = next((item for item in schedules[date] if _name_key(((item.get("teams") or {}).get("away") or {}).get("team", {}).get("name")) == away_key and _name_key(((item.get("teams") or {}).get("home") or {}).get("team", {}).get("name")) == home_key), None)
        if not game:
            skipped += 1
            continue
        game_pk = game.get("gamePk")
        teams = game.get("teams", {}) if isinstance(game.get("teams"), dict) else {}
        away = teams.get("away", {}) if isinstance(teams.get("away"), dict) else {}
        home = teams.get("home", {}) if isinstance(teams.get("home"), dict) else {}
        try:
            lineups, lineup_status = _mlb_lineup(game_pk)
        except requests.RequestException as error:
            lineups, lineup_status = {"away": [], "home": []}, "unavailable"
            errors.append(f"{event_id}: lineup {error.response.status_code if error.response else 'request error'}")
        venue = game.get("venue", {}) if isinstance(game.get("venue"), dict) else {}
        weather = game.get("weather", {}) if isinstance(game.get("weather"), dict) else {}
        record = {
            "id": hashlib.sha256(f"mlb-pregame-context|{taken_at}|{event_id}".encode()).hexdigest()[:32],
            "sport": "mlb", "record_type": "pregame_context", "taken_at": taken_at, "event_id": event_id,
            "game_pk": game_pk, "game": f"{event.get('away_team')} @ {event.get('home_team')}", "game_date": date,
            "commence_time": event.get("commence_time"), "status": ((game.get("status") or {}).get("abstractGameState")),
            "venue": {"id": venue.get("id"), "name": venue.get("name")}, "weather": weather,
            "away_probable_pitcher": _mlb_pitcher_context(away.get("probablePitcher")),
            "home_probable_pitcher": _mlb_pitcher_context(home.get("probablePitcher")),
            "lineup_status": lineup_status, "lineups": lineups,
            "source": "MLB Stats API pregame schedule and boxscore snapshot",
        }
        if store:
            store.collection("prediction_pregame_context_snapshots").document(record["id"]).set(record)
        else:
            _memory_backtests[record["id"]] = record
        stored += 1
    return jsonify({"success": True, "isolated": True, "record_type": "pregame_context", "taken_at": taken_at, "events_checked": len(events), "stored": stored, "skipped": skipped, "errors": errors[:10], "message": "Stored timestamped MLB pregame context. No prediction or live-model change was made."})


@prediction_ledger_bp.post("/snapshots/mlb/moneyline-context")
def snapshot_mlb_moneyline_context():
    """Persist an auditable pregame moneyline + available game-context record.

    This is the training data collection step for a future moneyline model. It
    makes no prediction and skips games at or after first pitch, so later model
    work cannot accidentally use postgame prices or information.
    """
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    try:
        max_events = min(15, max(1, int(request.args.get("max_events") or 15)))
    except ValueError:
        max_events = 15
    taken_at, stored, skipped = _now(), 0, 0
    errors: list[str] = []
    store = _store()
    schedules: dict[str, list[dict[str, Any]]] = {}
    try:
        events = _current_mlb_moneyline_events()
    except requests.RequestException as error:
        return jsonify({"error": f"Current MLB moneyline lookup failed ({error.response.status_code if error.response else 'request error'})."}), 502
    eligible = [event for event in events if not _has_started(event.get("commence_time"))][:max_events]
    for event in eligible:
        event_id, commence_time = str(event.get("id") or ""), str(event.get("commence_time") or "")
        game_date = commence_time[:10]
        if not event_id or not game_date:
            skipped += 1
            continue
        consensus = _pregame_moneyline_consensus(event)
        if consensus is None:
            skipped += 1
            continue
        try:
            if game_date not in schedules:
                schedules[game_date] = _mlb_schedule(game_date)
        except requests.RequestException as error:
            errors.append(f"{event_id}: schedule {error.response.status_code if error.response else 'request error'}")
            continue
        away_key, home_key = _name_key(event.get("away_team")), _name_key(event.get("home_team"))
        game = next((item for item in schedules[game_date] if _name_key(((item.get("teams") or {}).get("away") or {}).get("team", {}).get("name")) == away_key and _name_key(((item.get("teams") or {}).get("home") or {}).get("team", {}).get("name")) == home_key), None)
        context_status = "available" if game else "unavailable"
        lineups, lineup_status = {"away": [], "home": []}, "unavailable"
        venue: dict[str, Any] = {}
        weather: dict[str, Any] = {}
        away_pitcher = home_pitcher = None
        game_pk = None
        if game:
            game_pk = game.get("gamePk")
            teams = game.get("teams", {}) if isinstance(game.get("teams"), dict) else {}
            away = teams.get("away", {}) if isinstance(teams.get("away"), dict) else {}
            home = teams.get("home", {}) if isinstance(teams.get("home"), dict) else {}
            venue = game.get("venue", {}) if isinstance(game.get("venue"), dict) else {}
            weather = game.get("weather", {}) if isinstance(game.get("weather"), dict) else {}
            away_pitcher, home_pitcher = _mlb_pitcher_context(away.get("probablePitcher")), _mlb_pitcher_context(home.get("probablePitcher"))
            try:
                lineups, lineup_status = _mlb_lineup(game_pk)
            except requests.RequestException as error:
                errors.append(f"{event_id}: lineup {error.response.status_code if error.response else 'request error'}")
        record = {
            "id": hashlib.sha256(f"mlb-moneyline-context|{taken_at}|{event_id}".encode()).hexdigest()[:32],
            "sport": "mlb", "record_type": "pregame_moneyline_context", "isolation": "forward_moneyline_research",
            "eligible_for_live_calibration": False, "taken_at": taken_at, "event_id": event_id, "game_pk": game_pk,
            "game": f"{event.get('away_team')} @ {event.get('home_team')}", "game_date": game_date, "commence_time": commence_time,
            "market": consensus, "context_status": context_status, "venue": {"id": venue.get("id"), "name": venue.get("name")},
            "weather": weather, "away_probable_pitcher": away_pitcher, "home_probable_pitcher": home_pitcher,
            "lineup_status": lineup_status, "lineups": lineups, "bullpen_context_status": "not_collected_yet",
            "source": "The Odds API current multi-book moneyline + MLB Stats API pregame context",
        }
        if store:
            store.collection("prediction_mlb_moneyline_context_snapshots").document(record["id"]).set(record)
        else:
            _memory_backtests[record["id"]] = record
        stored += 1
    return jsonify({"success": True, "isolated": True, "record_type": "pregame_moneyline_context", "taken_at": taken_at, "events_checked": len(events), "eligible_pregame_events": len(eligible), "stored": stored, "skipped": skipped, "errors": errors[:10], "message": "Stored pregame multi-book moneylines with available lineup, pitcher, venue, and weather context. Records are research-only and cannot change live recommendations."})


def _mlb_verified_final_score(game_pk: Any, game_date: str) -> dict[str, Any] | None:
    """Use the official MLB schedule result only when the game is final."""
    try:
        game = next((item for item in _mlb_schedule(game_date) if str(item.get("gamePk")) == str(game_pk)), None)
    except requests.RequestException:
        return None
    if not game or str(((game.get("status") or {}).get("abstractGameState") or "")).casefold() != "final":
        return None
    teams = game.get("teams", {}) if isinstance(game.get("teams"), dict) else {}
    away, home = teams.get("away", {}), teams.get("home", {})
    away_score, home_score = _number(away.get("score") if isinstance(away, dict) else None), _number(home.get("score") if isinstance(home, dict) else None)
    if away_score is None or home_score is None or away_score == home_score:
        return None
    return {"away_score": away_score, "home_score": home_score, "home_won": home_score > away_score, "status": "Final", "provider": "MLB Stats API final schedule"}


@prediction_ledger_bp.post("/snapshots/mlb/grade-moneyline-context")
def grade_mlb_moneyline_context():
    """Attach verified final winners to forward moneyline-context observations."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    requested_date = str(request.args.get("date") or "")
    if requested_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", requested_date):
        return jsonify({"error": "date must use YYYY-MM-DD."}), 400
    store = _store()
    if store:
        rows = [(document.id, document.to_dict() or {}) for document in store.collection("prediction_mlb_moneyline_context_snapshots").stream()]
    else:
        rows = [(record_id, row) for record_id, row in _memory_backtests.items() if row.get("record_type") == "pregame_moneyline_context"]
    checked = settled = pending = skipped = 0
    errors: list[str] = []
    for record_id, row in rows:
        if row.get("record_type") != "pregame_moneyline_context" or row.get("result"):
            continue
        if requested_date and row.get("game_date") != requested_date:
            continue
        checked += 1
        game_pk, game_date = row.get("game_pk"), str(row.get("game_date") or "")
        if not game_pk or not game_date:
            skipped += 1
            continue
        final = _mlb_verified_final_score(game_pk, game_date)
        if final is None:
            pending += 1
            continue
        update = {"result": final, "graded_at": _now(), "eligible_for_live_calibration": False}
        if store:
            store.collection("prediction_mlb_moneyline_context_snapshots").document(record_id).set(update, merge=True)
        else:
            _memory_backtests[record_id] = {**row, **update}
        settled += 1
    return jsonify({"success": True, "isolated": True, "record_type": "pregame_moneyline_context", "date": requested_date or None, "checked": checked, "settled": settled, "pending": pending, "skipped": skipped, "errors": errors[:10], "message": "Attached MLB Stats API verified final winners to forward moneyline-context observations. No live model changed."})


@prediction_ledger_bp.post("/backtest/mlb/moneyline-baseline")
def backfill_historical_mlb_moneyline_baseline():
    """Import historical pregame h2h prices paired with verified final winners.

    These rows establish only a market baseline.  They deliberately do not
    claim historical lineup, weather, or bullpen context that was not captured
    at the time, so they cannot train the future context-feature model.
    """
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    date, snapshot = str(request.args.get("date") or ""), str(request.args.get("snapshot") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", snapshot):
        return jsonify({"error": "Provide date=YYYY-MM-DD and snapshot=YYYY-MM-DDTHH:MM:SSZ."}), 400
    try:
        max_events = min(3, max(1, int(request.args.get("max_events") or 3)))
    except ValueError:
        max_events = 3
    commit = str(request.args.get("commit") or "").lower() in {"1", "true", "yes"}
    try:
        captured = datetime.fromisoformat(snapshot.replace("Z", "+00:00"))
        events = [event for event in _historical_events(snapshot) if not _has_started_at(event.get("commence_time"), captured)][:max_events]
    except requests.RequestException as error:
        return jsonify({"error": f"Historical MLB event lookup failed ({error.response.status_code if error.response else 'request error'})."}), 502
    preview = [{"event_id": event.get("id"), "game": f"{event.get('away_team')} @ {event.get('home_team')}", "commence_time": event.get("commence_time")} for event in events]
    if not commit:
        return jsonify({"success": True, "preview": True, "date": date, "snapshot": snapshot, "events": preview, "estimated_historical_credits": len(events) * 30, "message": "Review the event list and estimate, then rerun with commit=true. Historical records are market-baseline research only."})
    store = _store()
    schedules: dict[str, list[dict[str, Any]]] = {}
    stored = skipped = 0
    errors: list[str] = []
    for event in events:
        event_id, game_date = str(event.get("id") or ""), str(event.get("commence_time") or "")[:10]
        if not event_id or not game_date:
            skipped += 1
            continue
        try:
            odds = _historical_mlb_moneyline_odds(event_id, snapshot)
            consensus = _pregame_moneyline_consensus({**event, **odds})
            if game_date not in schedules:
                schedules[game_date] = _mlb_schedule(game_date)
        except requests.RequestException as error:
            errors.append(f"{event_id}: {error.response.status_code if error.response else 'request error'}")
            continue
        if consensus is None:
            skipped += 1
            continue
        away_key, home_key = _name_key(event.get("away_team")), _name_key(event.get("home_team"))
        game = next((item for item in schedules[game_date] if _name_key(((item.get("teams") or {}).get("away") or {}).get("team", {}).get("name")) == away_key and _name_key(((item.get("teams") or {}).get("home") or {}).get("team", {}).get("name")) == home_key), None)
        final = _mlb_verified_final_score(game.get("gamePk"), game_date) if game else None
        if not game or final is None:
            skipped += 1
            continue
        record = {
            "id": hashlib.sha256(f"historical-mlb-moneyline|{snapshot}|{event_id}".encode()).hexdigest()[:32],
            "sport": "mlb", "record_type": "historical_pregame_moneyline_baseline", "isolation": "historical_market_baseline",
            "eligible_for_live_calibration": False, "event_id": event_id, "game_pk": game.get("gamePk"),
            "game": f"{event.get('away_team')} @ {event.get('home_team')}", "game_date": game_date, "commence_time": event.get("commence_time"),
            "snapshot": snapshot, "market": consensus, "context_status": "not_historically_captured", "result": final,
            "source": "The Odds API historical multi-book moneyline + MLB Stats API verified final",
        }
        if store:
            store.collection("prediction_mlb_moneyline_context_snapshots").document(record["id"]).set(record)
        else:
            _memory_backtests[record["id"]] = record
        stored += 1
    return jsonify({"success": True, "preview": False, "isolated": True, "date": date, "snapshot": snapshot, "events": preview, "stored": stored, "skipped": skipped, "errors": errors[:10], "message": "Stored historical pregame moneylines with verified final winners as a market-baseline dataset. No missing context was inferred."})


@prediction_ledger_bp.get("/backtest/mlb/moneyline-baseline/report")
def report_historical_mlb_moneyline_baseline():
    """Read-only calibration report for historical pregame moneyline baselines."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    store = _store()
    if store:
        rows = [document.to_dict() or {} for document in store.collection("prediction_mlb_moneyline_context_snapshots").where("record_type", "==", "historical_pregame_moneyline_baseline").stream()]
    else:
        rows = [row for row in _memory_backtests.values() if row.get("record_type") == "historical_pregame_moneyline_baseline"]
    evaluated: list[tuple[dict[str, Any], float, bool]] = []
    for row in rows:
        market, result = row.get("market"), row.get("result")
        probability = _number(market.get("fair_home_win_probability")) if isinstance(market, dict) else None
        home_won = result.get("home_won") if isinstance(result, dict) else None
        if probability is None or not isinstance(home_won, bool):
            continue
        evaluated.append((row, probability / 100, home_won))
    if not evaluated:
        return jsonify({"success": True, "isolated": True, "records_found": len(rows), "samples": 0, "message": "No settled historical moneyline-baseline records are available yet."})
    buckets: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for _, probability, home_won in evaluated:
        lower = min(90, int(probability * 100) // 10 * 10)
        buckets[f"{lower}-{lower + 9}%"].append((probability, home_won))
    by_probability_band = {
        label: {
            "samples": len(values), "average_fair_home_win_probability": round(sum(probability for probability, _ in values) / len(values) * 100, 1),
            "actual_home_win_rate": round(sum(home_won for _, home_won in values) / len(values) * 100, 1),
            "brier_score": round(sum((probability - int(home_won)) ** 2 for probability, home_won in values) / len(values), 4),
        }
        for label, values in sorted(buckets.items())
    }
    samples = len(evaluated)
    favorite_correct = sum((home_won if probability >= .5 else not home_won) for _, probability, home_won in evaluated)
    dates = sorted(str(row.get("game_date") or "") for row, _, _ in evaluated if row.get("game_date"))
    return jsonify({
        "success": True, "isolated": True, "record_type": "historical_pregame_moneyline_baseline", "records_found": len(rows),
        "samples": samples, "date_range": {"first": dates[0] if dates else None, "last": dates[-1] if dates else None, "days": len(set(dates))},
        "overall": {
            "average_fair_home_win_probability": round(sum(probability for _, probability, _ in evaluated) / samples * 100, 1),
            "actual_home_win_rate": round(sum(home_won for _, _, home_won in evaluated) / samples * 100, 1),
            "brier_score": round(sum((probability - int(home_won)) ** 2 for _, probability, home_won in evaluated) / samples, 4),
            "favorite_accuracy": round(favorite_correct / samples * 100, 1),
        },
        "by_home_probability_band": by_probability_band,
        "minimums": {"market_baseline_samples": 200, "context_model_training_samples": 500},
        "message": "Historical market-baseline calibration only. These rows lack historical lineup, weather, pitcher, and bullpen snapshots, so they cannot validate a context model or create a recommendation.",
    })


@prediction_ledger_bp.post("/snapshots/mlb/grade-market-consensus")
def grade_mlb_market_consensus():
    """Attach verified final results to forward MLB consensus observations."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    date = str(request.args.get("date") or (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat())
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return jsonify({"error": "date must use YYYY-MM-DD."}), 400
    store = _store()
    if store:
        rows = [snapshot.to_dict() or {} for snapshot in store.collection("prediction_market_snapshots").where("record_type", "==", "pregame_market_consensus").stream()]
    else:
        rows = list(_memory_backtests.values())
    rows = [row for row in rows if row.get("consensus_method") == "median_devig_per_book_v2" and row.get("game_date") == date and not row.get("settled_at")]
    game_cache: dict[str, tuple[dict[str, Any] | None, dict[str, dict[str, Any]]]] = {}
    checked = settled = pending = skipped = 0
    errors: list[str] = []
    for row in rows:
        checked += 1
        game_label = str(row.get("game") or "")
        if game_label not in game_cache:
            teams = [team.strip() for team in game_label.split("@")]
            if len(teams) != 2:
                game_cache[game_label] = (None, {})
            else:
                try:
                    game = _mlb_game_for_event(date, {"away_team": teams[0], "home_team": teams[1]})
                    stats = _mlb_game_stats(game.get("id")) if game and "final" in str(game.get("status") or "").lower() else {}
                    game_cache[game_label] = (game, stats)
                except (requests.RequestException, RuntimeError) as error:
                    errors.append(f"{game_label}: {error}")
                    game_cache[game_label] = (None, {})
        game, stats = game_cache[game_label]
        if not game or not stats:
            pending += 1
            continue
        market_key = str(row.get("market_key") or "")
        actual = stats.get(_name_key(row.get("player")), {}).get(MLB_BACKTEST_MARKETS.get(market_key, ("", ""))[1])
        line = _number(row.get("line"))
        if actual is None or line is None:
            skipped += 1
            continue
        outcome = "push" if actual == line else "over" if actual > line else "under"
        update = {"actual_value": actual, "outcome": outcome, "settled_at": _now(), "result_source": "BallDontLie MLB final game stats"}
        if store:
            store.collection("prediction_market_snapshots").document(str(row.get("id"))).set(update, merge=True)
        else:
            _memory_backtests[str(row.get("id"))] = {**row, **update}
        settled += 1
    return jsonify({"success": True, "isolated": True, "record_type": "pregame_market_consensus", "date": date, "checked": checked, "settled": settled, "pending": pending, "skipped": skipped, "errors": errors[:10], "message": "Attached verified final results to forward consensus observations. No live prediction change was made."})


@prediction_ledger_bp.post("/snapshots/wnba/grade-market-consensus")
def grade_wnba_market_consensus():
    """Attach final WNBA player statistics to forward research snapshots."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    date = str(request.args.get("date") or (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat())
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return jsonify({"error": "date must use YYYY-MM-DD."}), 400
    store = _store()
    if store:
        rows = [snapshot.to_dict() or {} for snapshot in store.collection("prediction_market_snapshots").where("record_type", "==", "pregame_wnba_market_consensus").stream()]
    else:
        rows = [row for row in _memory_backtests.values() if row.get("record_type") == "pregame_wnba_market_consensus"]
    rows = [row for row in rows if row.get("game_date") == date and not row.get("settled_at")]
    game_cache: dict[str, tuple[dict[str, Any] | None, dict[str, dict[str, float]]]] = {}
    checked = settled = pending = skipped = 0
    errors: list[str] = []
    for row in rows:
        checked += 1
        game_label = str(row.get("game") or "")
        if game_label not in game_cache:
            teams = [team.strip() for team in game_label.split("@")]
            if len(teams) != 2:
                game_cache[game_label] = (None, {})
            else:
                try:
                    game = _espn_wnba_final_game_for_event(date, {"away_team": teams[0], "home_team": teams[1]})
                    game_cache[game_label] = (game, _espn_wnba_box_stats(game.get("id")) if game else {})
                except requests.RequestException as error:
                    errors.append(f"{game_label}: {error.response.status_code if error.response else 'request error'}")
                    game_cache[game_label] = (None, {})
        game, stats = game_cache[game_label]
        if not game or not stats:
            pending += 1
            continue
        market_key = str(row.get("market_key") or "")
        field = WNBA_MARKETS.get(market_key, ("", ""))[1]
        actual, line = stats.get(_name_key(row.get("player")), {}).get(field), _number(row.get("line"))
        if actual is None or line is None:
            skipped += 1
            continue
        outcome = "push" if actual == line else "over" if actual > line else "under"
        update = {"actual_value": actual, "outcome": outcome, "settled_at": _now(), "result_source": "ESPN WNBA finalized box score"}
        if store:
            store.collection("prediction_market_snapshots").document(str(row.get("id"))).set(update, merge=True)
        else:
            _memory_backtests[str(row.get("id"))] = {**row, **update}
        settled += 1
    return jsonify({"success": True, "isolated": True, "record_type": "pregame_wnba_market_consensus", "season_phase": "regular_season", "date": date, "checked": checked, "settled": settled, "pending": pending, "skipped": skipped, "errors": errors[:10], "message": "Attached ESPN final WNBA player statistics to forward research observations. No player projection or live-model change was made."})


@prediction_ledger_bp.post("/snapshots/ncaaf/grade-market-consensus")
def grade_ncaaf_market_consensus():
    """Attach final NCAAF player statistics to saved forward prop observations."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    date = str(request.args.get("date") or (datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)).isoformat())
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return jsonify({"error": "date must use YYYY-MM-DD."}), 400
    store = _store()
    if store:
        rows = [snapshot.to_dict() or {} for snapshot in store.collection("prediction_market_snapshots").where("record_type", "==", "pregame_ncaaf_market_consensus").stream()]
    else:
        rows = [row for row in _memory_backtests.values() if row.get("record_type") == "pregame_ncaaf_market_consensus"]
    rows = [row for row in rows if row.get("game_date") == date and not row.get("settled_at")]
    game_cache: dict[str, tuple[dict[str, Any] | None, dict[str, dict[str, float]]]] = {}
    checked = settled = pending = skipped = 0
    errors: list[str] = []
    for row in rows:
        checked += 1
        game_label = str(row.get("game") or "")
        if game_label not in game_cache:
            teams = [team.strip() for team in game_label.split("@")]
            if len(teams) != 2:
                game_cache[game_label] = (None, {})
            else:
                try:
                    game = _espn_ncaaf_final_game_for_event(date, {"away_team": teams[0], "home_team": teams[1]})
                    game_cache[game_label] = (game, _espn_ncaaf_box_stats(game.get("id")) if game else {})
                except requests.RequestException as error:
                    errors.append(f"{game_label}: {error.response.status_code if error.response else 'request error'}")
                    game_cache[game_label] = (None, {})
        game, stats = game_cache[game_label]
        if not game or not stats:
            pending += 1
            continue
        field = NCAAF_PROP_MARKETS.get(str(row.get("market_key") or ""), ("", ""))[1]
        actual, line = stats.get(_name_key(row.get("player")), {}).get(field), _number(row.get("line"))
        if actual is None or line is None:
            skipped += 1
            continue
        outcome = "push" if actual == line else "over" if actual > line else "under"
        update = {"actual_value": actual, "outcome": outcome, "settled_at": _now(), "result_source": "ESPN NCAAF finalized box score"}
        if store:
            store.collection("prediction_market_snapshots").document(str(row.get("id"))).set(update, merge=True)
        else:
            _memory_backtests[str(row.get("id"))] = {**row, **update}
        settled += 1
    return jsonify({"success": True, "isolated": True, "record_type": "pregame_ncaaf_market_consensus", "date": date, "checked": checked, "settled": settled, "pending": pending, "skipped": skipped, "errors": errors[:10], "message": "Attached ESPN final NCAAF player statistics to forward research observations. No player projection or live-model change was made."})


@prediction_ledger_bp.post("/snapshots/ncaaf/grade-moneyline-context")
def grade_ncaaf_moneyline_context():
    """Attach provider-confirmed final scores to saved NCAAF moneyline records."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    date = str(request.args.get("date") or "")
    if date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return jsonify({"error": "date must use YYYY-MM-DD."}), 400
    store = _store()
    if store:
        rows = [(document.id, document.to_dict() or {}) for document in store.collection("prediction_ncaaf_moneyline_context_snapshots").stream()]
    else:
        rows = [(record_id, row) for record_id, row in _memory_backtests.items() if row.get("record_type") == "pregame_ncaaf_moneyline_context"]
    checked = settled = pending = skipped = 0
    errors: list[str] = []
    for record_id, row in rows:
        if row.get("record_type") != "pregame_ncaaf_moneyline_context" or row.get("result"):
            continue
        if date and row.get("game_date") != date:
            continue
        checked += 1
        teams = [team.strip() for team in str(row.get("game") or "").split("@")]
        game_date = str(row.get("game_date") or "")
        if len(teams) != 2 or not game_date:
            skipped += 1
            continue
        try:
            game = _espn_ncaaf_final_game_for_event(game_date, {"away_team": teams[0], "home_team": teams[1]})
        except requests.RequestException as error:
            errors.append(f"{row.get('game')}: {error.response.status_code if error.response else 'request error'}")
            continue
        if not game:
            pending += 1
            continue
        competition = (game.get("competitions") or [{}])[0]
        competitors = competition.get("competitors", []) if isinstance(competition, dict) else []
        sides = {str(item.get("homeAway") or "").lower(): item for item in competitors if isinstance(item, dict)}
        away_score, home_score = _number((sides.get("away") or {}).get("score")), _number((sides.get("home") or {}).get("score"))
        if away_score is None or home_score is None or away_score == home_score:
            skipped += 1
            continue
        update = {"result": {"away_score": away_score, "home_score": home_score, "home_won": home_score > away_score, "status": "Final", "provider": "ESPN public completed scoreboard"}, "graded_at": _now(), "eligible_for_live_calibration": False}
        if store:
            store.collection("prediction_ncaaf_moneyline_context_snapshots").document(record_id).set(update, merge=True)
        else:
            _memory_backtests[record_id] = {**row, **update}
        settled += 1
    return jsonify({"success": True, "isolated": True, "record_type": "pregame_ncaaf_moneyline_context", "date": date or None, "checked": checked, "settled": settled, "pending": pending, "skipped": skipped, "errors": errors[:10], "message": "Attached ESPN provider-confirmed NCAAF final scores to forward moneyline observations. No live model changed."})


@prediction_ledger_bp.get("/snapshots/wnba/market-consensus/report")
def report_wnba_market_consensus():
    """Read-only calibration report for settled, forward WNBA market snapshots."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    store = _store()
    if store:
        rows = [snapshot.to_dict() or {} for snapshot in store.collection("prediction_market_snapshots").where("record_type", "==", "pregame_wnba_market_consensus").stream()]
    else:
        rows = [row for row in _memory_backtests.values() if row.get("record_type") == "pregame_wnba_market_consensus"]
    settled = [row for row in rows if _number(row.get("line")) is not None and _number(row.get("actual_value")) is not None and _number(row.get("fair_probability_over")) is not None and _number(row.get("actual_value")) != _number(row.get("line"))]
    by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in settled:
        by_market[str(row.get("market") or "Other")].append(row)

    def metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
        samples = len(items)
        outcomes = [float(item["actual_value"]) > float(item["line"]) for item in items]
        probabilities = [float(item["fair_probability_over"]) / 100 for item in items]
        return {
            "samples": samples,
            "actual_over_rate": round(sum(outcomes) / samples * 100, 1) if samples else None,
            "average_fair_over_probability": round(sum(probabilities) / samples * 100, 1) if samples else None,
            "brier_score": round(sum((probability - int(outcome)) ** 2 for probability, outcome in zip(probabilities, outcomes)) / samples, 4) if samples else None,
        }

    dates = sorted({str(row.get("game_date") or "") for row in settled if row.get("game_date")})
    return jsonify({
        "success": True, "isolated": True, "season_phase": "regular_season", "record_type": "pregame_wnba_market_consensus",
        "records_found": len(rows), "settled_two_sided_records": len(settled),
        "date_range": {"first": dates[0] if dates else None, "last": dates[-1] if dates else None, "days": len(dates)},
        "overall": metrics(settled), "by_market": {market: metrics(items) for market, items in sorted(by_market.items())},
        "minimums": {"research_audit_samples": 200, "future_model_training_samples": 500},
        "message": "Forward WNBA market-observation report only. It does not produce a player projection, recommendation, or live-model change.",
    })


@prediction_ledger_bp.post("/snapshots/mlb/historical-market-consensus")
def snapshot_historical_mlb_market_consensus():
    """Backfill verified, point-in-time historical consensus records for research.

    These records are permanently marked historical and cannot be treated as
    forward snapshots or used to alter live predictions automatically.
    """
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    date = str(request.args.get("date") or "")
    snapshot = str(request.args.get("snapshot") or f"{date}T13:00:00Z")
    requested = [value.strip() for value in str(request.args.get("markets") or "batter_hits").split(",") if value.strip()]
    markets = [market for market in requested if market in MLB_BACKTEST_MARKETS]
    try:
        max_events = min(3, max(1, int(request.args.get("max_events") or 3)))
    except ValueError:
        max_events = 3
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not snapshot.startswith(f"{date}T") or not markets:
        return jsonify({"error": "Provide a completed date=YYYY-MM-DD, a same-day pregame snapshot, and supported MLB markets."}), 400
    if date >= datetime.now(timezone.utc).date().isoformat():
        return jsonify({"error": "Historical consensus imports require a completed past date."}), 400
    try:
        events = _historical_events(snapshot)[:max_events]
    except requests.RequestException as error:
        return jsonify({"error": f"Historical event lookup failed ({error.response.status_code if error.response else 'request error'})."}), 502

    stored = skipped = 0
    errors: list[str] = []
    store = _store()
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
            odds = _historical_mlb_props(event_id, snapshot, markets)
        except (requests.RequestException, RuntimeError) as error:
            errors.append(f"{event_id}: {error}")
            continue
        consensus, incomplete_pairs = _multi_book_prop_consensus(odds, markets)
        skipped += incomplete_pairs
        for (market_key, player, line), books in consensus.items():
            if len(books) < 2:
                continue
            actual = actuals.get(_name_key(player), {}).get(MLB_BACKTEST_MARKETS[market_key][1])
            if actual is None:
                skipped += 1
                continue
            representative = _representative_market_consensus(books)
            if representative is None:
                skipped += 1
                continue
            over, under, fair_over, reference_bookmaker = representative
            record = {
                "id": hashlib.sha256(f"mlb-historical-market-consensus|{snapshot}|{event_id}|{market_key}|{player}|{line}".encode()).hexdigest()[:32],
                "sport": "mlb", "record_type": "historical_pregame_market_consensus", "isolation": "historical_backtest",
                "eligible_for_live_calibration": False, "taken_at": snapshot, "snapshot": snapshot, "event_id": event_id,
                "game": f"{event.get('away_team')} @ {event.get('home_team')}", "commence_time": event.get("commence_time"),
                "game_date": date, "player": player, "market_key": market_key, "market": MLB_BACKTEST_MARKETS[market_key][0],
                "line": line, "over_odds": over, "under_odds": under, "fair_probability_over": round(fair_over * 100, 2),
                "book_count": len(books), "bookmakers": [book["bookmaker"] for book in books], "reference_bookmaker": reference_bookmaker,
                "consensus_method": "median_devig_per_book_v2", "actual_value": actual,
                "source": "The Odds API historical multi-book player-prop snapshot; BallDontLie MLB final game stats",
            }
            if store:
                store.collection("prediction_market_snapshots").document(record["id"]).set(record, merge=True)
            else:
                _memory_backtests[record["id"]] = record
            stored += 1
    return jsonify({"success": True, "isolated": True, "eligible_for_live_calibration": False, "record_type": "historical_pregame_market_consensus", "date": date, "snapshot": snapshot, "events_checked": len(events), "markets": markets, "stored": stored, "skipped": skipped, "errors": errors[:10], "message": "Stored verified historical multi-book consensus observations. These are research-only and do not change live predictions."})


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


def _v26_calibration_key(market_key: str, raw_probability_over: float) -> str:
    return f"{market_key}__raw_p_{_bucket(raw_probability_over, 0.10)}"


def _v26_over_probability(profile: dict[str, Any], market_key: str, raw_probability_over: float) -> float | None:
    groups = profile.get("groups") if isinstance(profile.get("groups"), dict) else {}
    for key in (_v26_calibration_key(market_key, raw_probability_over), market_key, "global"):
        group = groups.get(key)
        if isinstance(group, dict) and _number(group.get("probability_over")) is not None:
            return float(group["probability_over"])
    return None


def _v27_over_probability(profile: dict[str, Any], raw_probability_over: float) -> float | None:
    """Apply the frozen monotonic logistic calibration to a raw Poisson probability."""
    intercept, slope = _number(profile.get("intercept")), _number(profile.get("slope"))
    if intercept is None or slope is None or not 0 < raw_probability_over < 1:
        return None
    bounded = min(0.999, max(0.001, raw_probability_over))
    value = intercept + slope * log(bounded / (1 - bounded))
    return max(0.01, min(0.99, 1 / (1 + exp(-value))))


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


@prediction_ledger_bp.post("/backtest/mlb/v2.6/calibrate")
def calibrate_mlb_v26():
    """Freeze a side-neutral projection calibration from pre-cutoff V1 data."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    training_end = str(request.args.get("training_end") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", training_end):
        return jsonify({"error": "Provide training_end=YYYY-MM-DD for the frozen V2.6 training window."}), 400
    raw_source = [record for record in _mlb_backtest_records("mlb-last10-pregame-v1") if str(record.get("game_date") or "") <= training_end and _number(record.get("projection")) is not None and _number(record.get("line")) is not None and _number(record.get("actual_value")) is not None]
    # V1 rows may have been rehydrated later with historical two-sided prices.
    # Keep one deterministic observation per player/market/game so those
    # duplicate snapshots cannot overweight the calibration profile.
    deduplicated: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for record in sorted(raw_source, key=lambda item: str(item.get("snapshot") or "")):
        identity = (
            str(record.get("event_id") or ""),
            _name_key(record.get("player")),
            str(record.get("market_key") or "batter_hits"),
            str(record.get("line") or ""),
            str(record.get("game_date") or ""),
        )
        deduplicated.setdefault(identity, record)
    source = list(deduplicated.values())
    if len(source) < 250:
        return jsonify({"error": "At least 250 settled V1 records are required before calibration.", "records": len(source)}), 409
    observations: list[tuple[str, float, int]] = []
    for record in source:
        projection, line = float(record["projection"]), float(record["line"])
        market = str(record.get("market_key") or "batter_hits")
        observations.append((market, poisson_over_probability(projection, line), int(float(record["actual_value"]) > line)))
    global_wins = sum(outcome for _, _, outcome in observations)
    global_probability = (global_wins + 25 * 0.5) / (len(observations) + 25)
    grouped: dict[str, list[int]] = defaultdict(list)
    for market, raw_probability, outcome in observations:
        grouped["global"].append(outcome)
        grouped[market].append(outcome)
        grouped[_v26_calibration_key(market, raw_probability)].append(outcome)
    market_probabilities: dict[str, float] = {}
    for key, outcomes in grouped.items():
        if "__raw_p_" not in key and key != "global":
            market_probabilities[key] = (sum(outcomes) + 30 * global_probability) / (len(outcomes) + 30)
    groups: dict[str, dict[str, Any]] = {}
    for key, outcomes in grouped.items():
        samples, wins = len(outcomes), sum(outcomes)
        if key == "global":
            probability = global_probability
        elif "__raw_p_" not in key:
            probability = market_probabilities[key]
        else:
            market = key.split("__raw_p_", 1)[0]
            probability = (wins + 40 * market_probabilities.get(market, global_probability)) / (samples + 40)
        groups[key] = {"samples": samples, "over_wins": wins, "probability_over": round(probability, 5)}
    profile = {"id": "mlb-v2.6", "model_version": "mlb-calibrated-directional-ev-v2.6", "training_end": training_end, "training_samples": len(source), "source_model_version": "mlb-last10-pregame-v1", "groups": groups, "created_at": _now(), "frozen": True}
    store = _store()
    if store:
        store.collection("prediction_model_calibrations").document("mlb-v2.6").set(profile)
    else:
        _memory_calibrations["mlb-v2.6"] = profile
    return jsonify({"success": True, "model": "v2.6", "training_end": training_end, "training_samples": len(source), "deduplicated_from": len(raw_source), "global_probability_over": round(global_probability * 100, 2), "groups": len(groups), "message": "Frozen side-neutral projection calibration created. Only import V2.6 backtests dated after training_end."})


@prediction_ledger_bp.post("/backtest/mlb/v2.7/calibrate")
def calibrate_mlb_v27():
    """Fit one frozen, monotonic Platt calibration on pre-cutoff V1 results."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    training_end = str(request.args.get("training_end") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", training_end):
        return jsonify({"error": "Provide training_end=YYYY-MM-DD for the frozen V2.7 training window."}), 400
    raw_source = [record for record in _mlb_backtest_records("mlb-last10-pregame-v1") if str(record.get("game_date") or "") <= training_end and _number(record.get("projection")) is not None and _number(record.get("line")) is not None and _number(record.get("actual_value")) is not None]
    deduplicated: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for record in sorted(raw_source, key=lambda item: str(item.get("snapshot") or "")):
        identity = (str(record.get("event_id") or ""), _name_key(record.get("player")), str(record.get("market_key") or "batter_hits"), str(record.get("line") or ""), str(record.get("game_date") or ""))
        deduplicated.setdefault(identity, record)
    source = list(deduplicated.values())
    if len(source) < 200:
        return jsonify({"error": "At least 200 settled V1 records are required before calibration.", "records": len(source)}), 409
    observations: list[tuple[float, int]] = []
    for record in source:
        raw_probability = poisson_over_probability(float(record["projection"]), float(record["line"]))
        bounded = min(0.999, max(0.001, raw_probability))
        observations.append((log(bounded / (1 - bounded)), int(float(record["actual_value"]) > float(record["line"]))))
    actual_mean = sum(outcome for _, outcome in observations) / len(observations)
    baseline = log(max(0.001, min(0.999, actual_mean)) / max(0.001, 1 - actual_mean))
    intercept, slope = baseline, 0.50
    # Averaged-gradient Platt scaling, regularized toward a modest monotonic
    # relationship.  The fit never uses any post-cutoff test outcome.
    for _ in range(1200):
        probabilities = [1 / (1 + exp(-(intercept + slope * value))) for value, _ in observations]
        gradient_intercept = sum(probability - outcome for probability, (_, outcome) in zip(probabilities, observations)) / len(observations) + 0.03 * (intercept - baseline)
        gradient_slope = sum((probability - outcome) * value for probability, (value, outcome) in zip(probabilities, observations)) / len(observations) + 0.08 * (slope - 0.50)
        intercept -= 0.04 * gradient_intercept
        slope = max(0.05, min(2.0, slope - 0.02 * gradient_slope))
    profile = {"id": "mlb-v2.7", "model_version": "mlb-continuous-market-anchored-ev-v2.7", "training_end": training_end, "training_samples": len(source), "deduplicated_from": len(raw_source), "source_model_version": "mlb-last10-pregame-v1", "intercept": round(intercept, 7), "slope": round(slope, 7), "training_actual_over_rate": round(actual_mean * 100, 2), "created_at": _now(), "frozen": True}
    store = _store()
    if store:
        store.collection("prediction_model_calibrations").document("mlb-v2.7").set(profile)
    else:
        _memory_calibrations["mlb-v2.7"] = profile
    return jsonify({"success": True, "model": "v2.7", "training_end": training_end, "training_samples": len(source), "deduplicated_from": len(raw_source), "training_actual_over_rate": profile["training_actual_over_rate"], "intercept": profile["intercept"], "slope": profile["slope"], "market_anchor_weight": 75, "message": "Frozen continuous calibration created. Only import V2.7 backtests dated after training_end."})


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
        "average_projection_market_signal": _mean_derived_signal(items),
    }


def _projection_market_signal(record: dict[str, Any]) -> float | None:
    """Recover the player-vs-fair-market signal from the immutable ledger."""
    stored = _number(record.get("projection_market_signal"))
    if stored is not None:
        return stored / 100
    projection, line = _number(record.get("projection")), _number(record.get("line"))
    fair_over = _fair_over_probability(record.get("over_odds"), record.get("under_odds"))
    if projection is None or line is None or fair_over is None:
        return None
    return poisson_over_probability(projection, line) - fair_over


def _mean_derived_signal(items: list[dict[str, Any]]) -> float | None:
    signals = [_projection_market_signal(item) for item in items]
    usable = [signal for signal in signals if signal is not None]
    return round(sum(usable) / len(usable) * 100, 3) if usable else None


def _mlb_backtest_diagnostics(model_version: str) -> dict[str, Any]:
    """Read-only analysis of selection behavior; it cannot tune any model."""
    all_records = _mlb_backtest_records(model_version)
    candidates = [record for record in all_records if record.get("candidate") is True]
    by_side: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_ev_band: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_gap_band: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_odds_band: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_projection_market_signal: dict[str, list[dict[str, Any]]] = defaultdict(list)
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
        signal = _projection_market_signal(record)
        signal_label = "Unavailable" if signal is None else "Over signal 5%+" if signal >= 0.05 else "Over signal 2.5–4.99%" if signal >= 0.025 else "Under signal 5%+" if signal <= -0.05 else "Under signal 2.5–4.99%" if signal <= -0.025 else "Neutral (<2.5%)"
        by_projection_market_signal[signal_label].append(record)
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
        "by_projection_market_signal": {name: _diagnostic_summary(rows) for name, rows in by_projection_market_signal.items()},
        "projection_market_signal_coverage": round(sum(_projection_market_signal(record) is not None for record in candidates) / len(candidates), 3) if candidates else 0.0,
        "warnings": warnings,
        "message": "Diagnostic report only. It does not modify thresholds, calibration, or live predictions.",
    }


def _mlb_backtest_evaluation(model_version: str = "mlb-last10-pregame-v1") -> dict[str, Any]:
    all_records = _mlb_backtest_records(model_version)
    candidate_only = model_version.startswith(("mlb-probability-ev-v2", "mlb-empirical-probability-ev-v2", "mlb-market-relative-ev-v2", "mlb-projection-relative-ev-v2", "mlb-directional-projection-ev-v2", "mlb-calibrated-directional-ev-v2", "mlb-continuous-market-anchored-ev-v2"))
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
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not markets or model not in {"v1", "v2", "v2.1", "v2.2", "v2.3", "v2.4", "v2.5", "v2.6", "v2.7"}:
        return jsonify({"error": "Provide date=YYYY-MM-DD and one or more supported MLB markets."}), 400
    if not snapshot.startswith(f"{date}T"):
        return jsonify({"error": "snapshot must be a pregame UTC timestamp on the same date as date (for example, 2026-08-14T13:00:00Z)."}), 400
    if date >= datetime.now(timezone.utc).date().isoformat():
        return jsonify({"error": "Historical backtests require a completed past date."}), 400
    v22_profile = _load_v22_profile() if model == "v2.2" else None
    v23_profile = _load_profile("mlb-v2.3") if model == "v2.3" else None
    v26_profile = _load_profile("mlb-v2.6") if model == "v2.6" else None
    v27_profile = _load_profile("mlb-v2.7") if model == "v2.7" else None
    if model == "v2.2" and (not v22_profile or str(v22_profile.get("training_end") or "") >= date):
        return jsonify({"error": "V2.2 requires a frozen profile with training_end before the imported game date."}), 409
    if model == "v2.3" and (not v23_profile or str(v23_profile.get("training_end") or "") >= date):
        return jsonify({"error": "V2.3 requires a frozen profile with training_end before the imported game date."}), 409
    if model == "v2.6" and (not v26_profile or str(v26_profile.get("training_end") or "") >= date):
        return jsonify({"error": "V2.6 requires a frozen profile with training_end before the imported game date."}), 409
    if model == "v2.7" and (not v27_profile or str(v27_profile.get("training_end") or "") >= date):
        return jsonify({"error": "V2.7 requires a frozen profile with training_end before the imported game date."}), 409
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
                    if model in {"v2.3", "v2.4", "v2.5", "v2.6", "v2.7"}:
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
                    if model in {"v2.3", "v2.4", "v2.5", "v2.6", "v2.7"}:
                        two_sided_complete_pairs.add(pair_identity)
                    v2_version = "mlb-probability-ev-v2.1" if model == "v2.1" else "mlb-probability-ev-v2"
                    calibrated_probability = _v22_over_probability(v22_profile, key, line, projection) if v22_profile else None
                    relative_residual = _v23_residual(v23_profile, key, line, projection) if v23_profile else None
                    v26_raw_probability = poisson_over_probability(projection, line) if model == "v2.6" else None
                    v26_probability = _v26_over_probability(v26_profile, key, v26_raw_probability) if v26_profile and v26_raw_probability is not None else None
                    v27_raw_probability = poisson_over_probability(projection, line) if model == "v2.7" else None
                    v27_probability = _v27_over_probability(v27_profile, v27_raw_probability) if v27_profile and v27_raw_probability is not None else None
                    model_output = evaluate_continuous_market_anchored_prop(season_rate=projection, line=line, over_odds=prices.get("over"), under_odds=prices.get("under"), sample_games=sample_games, calibrated_over_probability=v27_probability) if model == "v2.7" else evaluate_calibrated_directional_prop(season_rate=projection, line=line, over_odds=prices.get("over"), under_odds=prices.get("under"), sample_games=sample_games, calibrated_over_probability=v26_probability) if model == "v2.6" else evaluate_directional_projection_prop(season_rate=projection, line=line, over_odds=prices.get("over"), under_odds=prices.get("under"), sample_games=sample_games) if model == "v2.5" else evaluate_projection_relative_prop(season_rate=projection, line=line, over_odds=prices.get("over"), under_odds=prices.get("under"), sample_games=sample_games) if model == "v2.4" else evaluate_market_relative_prop(season_rate=projection, line=line, over_odds=prices.get("over"), under_odds=prices.get("under"), sample_games=sample_games, historical_residual=relative_residual) if model == "v2.3" else evaluate_calibrated_prop(season_rate=projection, line=line, over_odds=prices.get("over"), under_odds=prices.get("under"), sample_games=sample_games, calibrated_over_probability=calibrated_probability) if model == "v2.2" else evaluate_mlb_v2(season_rate=projection, line=line, over_odds=prices.get("over"), under_odds=prices.get("under"), sample_games=sample_games if model == "v2.1" else None, model_version=v2_version) if model in {"v2", "v2.1"} else None
                    if model in {"v2", "v2.1", "v2.2", "v2.3", "v2.4", "v2.5", "v2.6", "v2.7"} and not model_output:
                        skipped += 1
                        continue
                    side = str(model_output["selected_side"]) if model_output else "Over" if projection >= line else "Under"
                    model_version = str(model_output["model_version"]) if model_output else "mlb-last10-pregame-v1"
                    stored_projection = float(model_output["projection"]) if model_output else projection
                    record_id = hashlib.sha256(f"mlb-backtest|{model_version}|{event_id}|{player}|{key}|{line}|{snapshot}".encode()).hexdigest()[:32]
                    outcome = "push" if actual == line else "won" if (side == "Over" and actual > line) or (side == "Under" and actual < line) else "lost"
                    _backtest_store({"id": record_id, "isolation": "historical_backtest", "eligible_for_live_calibration": False, "sport": "mlb", "event_id": event_id, "game": f"{event.get('away_team')} @ {event.get('home_team')}", "player": player, "market": MLB_BACKTEST_MARKETS[key][0], "market_key": key, "line": line, "projection": stored_projection, "side": side, "odds": prices.get(side.lower()), "over_odds": prices.get("over"), "under_odds": prices.get("under"), "actual_value": actual, "outcome": outcome, "snapshot": snapshot, "game_date": date, "model_version": model_version, "model_probability": model_output.get("selected_probability") if model_output else None, "expected_value": model_output.get("expected_value") if model_output else None, "fair_probability_over": model_output.get("fair_probability_over") if model_output else None, "projection_probability_over": model_output.get("projection_probability_over") if model_output else None, "projection_market_signal": model_output.get("raw_projection_market_signal") if model_output else None, "candidate": model_output.get("candidate") if model_output else None, "line_source": "The Odds API historical event snapshot", "result_source": "BallDontLie MLB final game stats", "created_at": _now()})
                    imported += 1
            if model not in {"v2.3", "v2.4", "v2.5", "v2.6", "v2.7"}:
                break  # one bookmaker avoids duplicate line versions
    return jsonify({"success": True, "preview": False, "isolated": True, "eligible_for_live_calibration": False, "date": date, "snapshot": snapshot, "events": preview, "imported": imported, "skipped": skipped, "errors": errors[:10], "message": "Backtest records are isolated from live calibration. Review their performance before promoting a validated model version."})


@prediction_ledger_bp.get("/backtest/mlb/summary")
def historical_mlb_backtest_summary():
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    model = str(request.args.get("model") or "v1").lower()
    versions = {"v1": "mlb-last10-pregame-v1", "v2": "mlb-probability-ev-v2", "v2.1": "mlb-probability-ev-v2.1", "v2.2": "mlb-empirical-probability-ev-v2.2", "v2.3": "mlb-market-relative-ev-v2.3", "v2.4": "mlb-projection-relative-ev-v2.4", "v2.5": "mlb-directional-projection-ev-v2.5", "v2.6": "mlb-calibrated-directional-ev-v2.6", "v2.7": "mlb-continuous-market-anchored-ev-v2.7"}
    if model not in versions:
        return jsonify({"error": "model must be v1, v2, v2.1, v2.2, v2.3, v2.4, v2.5, v2.6, or v2.7"}), 400
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
    versions = {"v1": "mlb-last10-pregame-v1", "v2": "mlb-probability-ev-v2", "v2.1": "mlb-probability-ev-v2.1", "v2.2": "mlb-empirical-probability-ev-v2.2", "v2.3": "mlb-market-relative-ev-v2.3", "v2.4": "mlb-projection-relative-ev-v2.4", "v2.5": "mlb-directional-projection-ev-v2.5", "v2.6": "mlb-calibrated-directional-ev-v2.6", "v2.7": "mlb-continuous-market-anchored-ev-v2.7"}
    if model not in versions:
        return jsonify({"error": "model must be v1, v2, v2.1, v2.2, v2.3, v2.4, v2.5, v2.6, or v2.7"}), 400
    return jsonify({**_mlb_backtest_evaluation(versions[model]), "model": model})


@prediction_ledger_bp.get("/backtest/mlb/diagnostics")
def historical_mlb_backtest_diagnostics():
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    model = str(request.args.get("model") or "v2.4").lower()
    versions = {"v1": "mlb-last10-pregame-v1", "v2": "mlb-probability-ev-v2", "v2.1": "mlb-probability-ev-v2.1", "v2.2": "mlb-empirical-probability-ev-v2.2", "v2.3": "mlb-market-relative-ev-v2.3", "v2.4": "mlb-projection-relative-ev-v2.4", "v2.5": "mlb-directional-projection-ev-v2.5", "v2.6": "mlb-calibrated-directional-ev-v2.6", "v2.7": "mlb-continuous-market-anchored-ev-v2.7"}
    if model not in versions:
        return jsonify({"error": "model must be v1, v2, v2.1, v2.2, v2.3, v2.4, v2.5, v2.6, or v2.7"}), 400
    return jsonify({**_mlb_backtest_diagnostics(versions[model]), "model": model})


@prediction_ledger_bp.get("/backtest/mlb/audit")
def historical_mlb_backtest_audit():
    """Expose a small, immutable sample for model/data-quality review."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    model = str(request.args.get("model") or "v2.6").lower()
    versions = {"v1": "mlb-last10-pregame-v1", "v2": "mlb-probability-ev-v2", "v2.1": "mlb-probability-ev-v2.1", "v2.2": "mlb-empirical-probability-ev-v2.2", "v2.3": "mlb-market-relative-ev-v2.3", "v2.4": "mlb-projection-relative-ev-v2.4", "v2.5": "mlb-directional-projection-ev-v2.5", "v2.6": "mlb-calibrated-directional-ev-v2.6", "v2.7": "mlb-continuous-market-anchored-ev-v2.7"}
    if model not in versions:
        return jsonify({"error": "model must be v1, v2, v2.1, v2.2, v2.3, v2.4, v2.5, v2.6, or v2.7"}), 400
    try:
        limit = min(50, max(1, int(request.args.get("limit") or 20)))
    except ValueError:
        limit = 20
    records = _mlb_backtest_records(versions[model])
    candidates = [record for record in records if record.get("candidate") is True]

    def implied_probability(price: Any) -> float | None:
        value = _number(price)
        if value is None or value == 0:
            return None
        return round((100 / (value + 100) if value > 0 else -value / (-value + 100)) * 100, 2)

    samples = []
    for record in sorted(candidates, key=lambda item: (str(item.get("game_date") or ""), str(item.get("player") or "")))[:limit]:
        samples.append({
            "date": record.get("game_date"), "game": record.get("game"), "player": record.get("player"), "market": record.get("market"),
            "line": record.get("line"), "projection": record.get("projection"), "actual": record.get("actual_value"), "side": record.get("side"),
            "outcome": record.get("outcome"), "selected_odds": record.get("odds"), "over_odds": record.get("over_odds"), "under_odds": record.get("under_odds"),
            "selected_implied_probability": implied_probability(record.get("odds")), "over_implied_probability": implied_probability(record.get("over_odds")), "under_implied_probability": implied_probability(record.get("under_odds")),
            "stored_fair_over_probability": record.get("fair_probability_over"), "model_probability": record.get("model_probability"),
            "projection_probability_over": record.get("projection_probability_over"), "projection_market_signal": record.get("projection_market_signal"), "expected_value": record.get("expected_value"),
        })
    return jsonify({"success": True, "isolated": True, "model": model, "candidate_records": len(candidates), "all_records": len(records), "sample_count": len(samples), "samples": samples, "message": "Audit report only. It does not modify historical records, calibration, or live predictions."})


@prediction_ledger_bp.post("/backtest/mlb/promotion")
def promote_historical_mlb_model():
    """Record a reviewed backtest decision; it never switches live logic itself."""
    if not _import_authorized():
        return jsonify({"error": "A valid import key or administrator session is required."}), 403
    model = str(request.args.get("model") or "v1").lower()
    versions = {"v1": "mlb-last10-pregame-v1", "v2": "mlb-probability-ev-v2", "v2.1": "mlb-probability-ev-v2.1", "v2.2": "mlb-empirical-probability-ev-v2.2", "v2.3": "mlb-market-relative-ev-v2.3", "v2.4": "mlb-projection-relative-ev-v2.4", "v2.5": "mlb-directional-projection-ev-v2.5", "v2.6": "mlb-calibrated-directional-ev-v2.6", "v2.7": "mlb-continuous-market-anchored-ev-v2.7"}
    if model not in versions:
        return jsonify({"error": "model must be v1, v2, v2.1, v2.2, v2.3, v2.4, v2.5, v2.6, or v2.7"}), 400
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
