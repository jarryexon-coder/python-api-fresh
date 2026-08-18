"""Current player-prop lines from The Odds API.

This is intentionally a line feed, not a synthetic projection generator.  When
the provider has no market for a sport or date the client receives an empty
slate instead of fabricated player cards.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests
from flask import Blueprint, jsonify, request


live_props_bp = Blueprint("live_props", __name__, url_prefix="/api")
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_projection_cache: dict[str, tuple[float, dict[str, dict[str, float]]]] = {}
_CACHE_SECONDS = 60
_PROJECTION_CACHE_SECONDS = 300


class ProviderRequestError(RuntimeError):
    """A provider error that is safe to return without leaking request URLs."""

SPORT_KEYS = {
    "nba": "basketball_nba",
    "nfl": "americanfootball_nfl",
    "mlb": "baseball_mlb",
}
MARKETS = {
    "nba": "player_points,player_rebounds,player_assists,player_threes",
    "nfl": "player_pass_yds,player_pass_tds,player_rush_yds,player_reception_yds,player_receptions",
    "mlb": "batter_hits,batter_runs_scored,batter_rbis,batter_home_runs,batter_total_bases,pitcher_strikeouts",
}


def _name_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _key() -> str | None:
    return os.getenv("THE_ODDS_API_KEY") or os.getenv("ODDS_API_KEY") or os.getenv("THEODDS_API_KEY")


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _market_label(value: str) -> str:
    return value.replace("batter_", "").replace("pitcher_", "").replace("player_", "").replace("_", " ").title()


def _mlb_projections() -> dict[str, dict[str, float]]:
    """Build transparent per-game MLB projections from current BDL stats."""
    cached = _projection_cache.get("mlb")
    if cached and time.time() - cached[0] < _PROJECTION_CACHE_SECONDS:
        return cached[1]
    key = os.getenv("BALLDONTLIE_API_KEY")
    if not key:
        return {}
    rows: list[dict[str, Any]] = []
    cursor: Any = None
    try:
        for _ in range(20):
            params: dict[str, Any] = {"season": datetime.now().year, "per_page": 100}
            if cursor is not None:
                params["cursor"] = cursor
            response = requests.get("https://api.balldontlie.io/mlb/v1/season_stats", headers={"Authorization": key, "Accept": "application/json"}, params=params, timeout=20)
            response.raise_for_status()
            payload = response.json()
            page = payload.get("data", []) if isinstance(payload, dict) else []
            rows.extend(row for row in page if isinstance(row, dict))
            cursor = payload.get("meta", {}).get("next_cursor") if isinstance(payload, dict) else None
            if not cursor or not page:
                break
    except requests.RequestException:
        return {}

    result: dict[str, dict[str, float]] = {}
    for row in rows:
        player = row.get("player") if isinstance(row.get("player"), dict) else {}
        name = player.get("full_name") or " ".join(filter(None, [player.get("first_name"), player.get("last_name")]))
        games = _number(row.get("batting_gp")) or _number(row.get("pitching_gp")) or 0
        if not name or not games:
            continue
        def per_game(key: str) -> float | None:
            value = _number(row.get(key))
            return round(value / games, 2) if value is not None else None
        values = {
            "batter_hits": per_game("batting_h"), "batter_runs_scored": per_game("batting_r"),
            "batter_rbis": per_game("batting_rbi"), "batter_home_runs": per_game("batting_hr"),
            "batter_total_bases": per_game("batting_tb"), "pitcher_strikeouts": per_game("pitching_k"),
        }
        result[_name_key(name)] = {metric: value for metric, value in values.items() if value is not None}
    _projection_cache["mlb"] = (time.time(), result)
    return result


def _nfl_projection_params() -> dict[str, Any]:
    return {
        "week": os.getenv("TANK01_NFL_PROJECTION_WEEK", "1"), "archiveSeason": os.getenv("TANK01_NFL_PROJECTION_SEASON", str(datetime.now().year)), "itemFormat": "list",
        "twoPointConversions": 2, "passYards": ".04", "passAttempts": "-.5", "passTD": 4, "passCompletions": 1, "passInterceptions": -2,
        "pointsPerReception": 1, "carries": ".2", "rushYards": ".1", "rushTD": 6, "fumbles": -2, "receivingYards": ".1", "receivingTD": 6,
        "targets": ".1", "fgMade": 3, "fgMissed": -1, "xpMade": 1, "xpMissed": -1,
    }


def _nfl_projections() -> dict[str, dict[str, float]]:
    cached = _projection_cache.get("nfl")
    if cached and time.time() - cached[0] < _PROJECTION_CACHE_SECONDS:
        return cached[1]
    key = os.getenv("RAPIDAPI_KEY_TANK01") or os.getenv("RAPIDAPI_KEY")
    if not key:
        return {}
    host = "tank01-nfl-live-in-game-real-time-statistics-nfl.p.rapidapi.com"
    try:
        response = requests.get(f"https://{host}/getNFLProjections", headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": host, "Accept": "application/json"}, params=_nfl_projection_params(), timeout=25)
        response.raise_for_status()
        payload = response.json()
        body = payload.get("body", payload) if isinstance(payload, dict) else {}
        raw = body.get("playerProjections", body) if isinstance(body, dict) else []
        rows = list(raw.values()) if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    except requests.RequestException:
        return {}
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("longName")
        if not name:
            continue
        passing = row.get("Passing") if isinstance(row.get("Passing"), dict) else {}
        rushing = row.get("Rushing") if isinstance(row.get("Rushing"), dict) else {}
        receiving = row.get("Receiving") if isinstance(row.get("Receiving"), dict) else {}
        values = {
            "player_pass_yds": _number(passing.get("passYds")), "player_pass_tds": _number(passing.get("passTD")),
            "player_rush_yds": _number(rushing.get("rushYds")), "player_reception_yds": _number(receiving.get("recYds")),
            "player_receptions": _number(receiving.get("receptions")),
        }
        result[_name_key(name)] = {metric: value for metric, value in values.items() if value is not None}
    _projection_cache["nfl"] = (time.time(), result)
    return result


def _projections(sport: str) -> tuple[dict[str, dict[str, float]], str | None]:
    if sport == "mlb":
        return _mlb_projections(), "BallDontLie MLB season-context projection"
    if sport == "nfl":
        return _nfl_projections(), "Tank01 NFL weekly projection"
    return {}, None


def _rows(sport: str) -> dict[str, Any]:
    key = _key()
    if not key:
        raise RuntimeError("THE_ODDS_API_KEY is not configured in Railway Variables.")
    sport_key = SPORT_KEYS[sport]
    # Player-prop markets are only available through the per-event Odds API
    # endpoint. A league-wide `/odds` request is rejected for these markets.
    try:
        response = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/events",
            params={"apiKey": key}, timeout=20,
        )
        if not response.ok:
            raise ProviderRequestError("The Odds API could not load the current event slate.")
        events = response.json()
    except requests.RequestException as error:
        raise ProviderRequestError("The Odds API event request failed.") from error
    if not isinstance(events, list):
        events = []

    projections, projection_source = _projections(sport)
    result: list[dict[str, Any]] = []
    for event in events[:12]:
        if not isinstance(event, dict):
            continue
        game = f"{event.get('away_team') or 'Away'} @ {event.get('home_team') or 'Home'}"
        event_id = event.get("id")
        if not event_id:
            continue
        try:
            response = requests.get(
                f"https://api.the-odds-api.com/v4/sports/{sport_key}/events/{event_id}/odds",
                params={"apiKey": key, "regions": "us", "markets": MARKETS[sport], "oddsFormat": "american"}, timeout=20,
            )
            # A given game can simply have no posted player markets. Continue
            # rather than replacing the entire real slate with a fallback.
            if not response.ok:
                continue
            event_odds = response.json()
        except requests.RequestException:
            continue
        for bookmaker in event_odds.get("bookmakers", []) if isinstance(event_odds, dict) else []:
            if not isinstance(bookmaker, dict):
                continue
            bookmaker_name = str(bookmaker.get("title") or bookmaker.get("key") or "Sportsbook")
            for market in bookmaker.get("markets", []):
                if not isinstance(market, dict):
                    continue
                market_key = str(market.get("key") or "")
                paired: dict[tuple[str, float], dict[str, Any]] = {}
                for outcome in market.get("outcomes", []):
                    if not isinstance(outcome, dict):
                        continue
                    outcome_name = str(outcome.get("name") or "").strip()
                    # Odds API normally uses ``description`` for the player and
                    # ``name`` for Over/Under.  Some bookmakers omit the former,
                    # so accept a non-side outcome name as the player instead.
                    player = str(
                        outcome.get("description")
                        or outcome.get("player")
                        or outcome.get("participant")
                        or (outcome_name if outcome_name.lower() not in {"over", "under"} else "")
                    ).strip()
                    line = _number(outcome.get("point"))
                    side = outcome_name.lower()
                    if not player or line is None or side not in {"over", "under"}:
                        continue
                    pair = paired.setdefault((player, line), {"over": None, "under": None})
                    pair[side] = _number(outcome.get("price"))
                for (player, line), prices in paired.items():
                    if prices["over"] is None and prices["under"] is None:
                        continue
                    projection = projections.get(_name_key(player), {}).get(market_key)
                    edge = round(((projection - line) / line) * 100, 1) if projection is not None and line else None
                    result.append({
                        "id": f"{event_id}:{bookmaker.get('key', 'book')}:{market_key}:{player}:{line}",
                        "player": player,
                        "team": "",
                        "market": _market_label(market_key),
                        "market_key": market_key,
                        "line": line,
                        "projection": projection,
                        "projection_available": projection is not None,
                        "projection_source": projection_source if projection is not None else "No matching current projection available",
                        "edge": edge,
                        "over_odds": prices["over"],
                        "under_odds": prices["under"],
                        "odds": prices["over"],
                        "game": game,
                        "game_id": event_id,
                        "commence_time": event.get("commence_time"),
                        "bookmaker": bookmaker_name,
                        "provider_updated_at": bookmaker.get("last_update") or event.get("commence_time"),
                        "is_real_data": True,
                    })
            # One sportsbook per event keeps the request inexpensive and avoids
            # displaying duplicate versions of the same current line.
            break
    return {
        "success": True,
        "data": result,
        "props": result,
        "count": len(result),
        "sport": sport,
        "source": f"The Odds API live player props + {projection_source}" if projection_source else "The Odds API live player props",
        "is_real_data": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cache_ttl_seconds": _CACHE_SECONDS,
    }


@live_props_bp.get("/live-props")
def live_props():
    sport = request.args.get("sport", "nba").lower()
    if sport not in SPORT_KEYS:
        return jsonify({"success": False, "error": "sport must be nba, nfl, or mlb"}), 400
    force = request.args.get("force", "").lower() in {"1", "true", "yes"}
    cached = _cache.get(sport)
    if not force and cached and time.time() - cached[0] < _CACHE_SECONDS:
        response = {**cached[1], "cached": True}
        return jsonify(response)
    try:
        response = _rows(sport)
        _cache[sport] = (time.time(), response)
        return jsonify({**response, "cached": False})
    except RuntimeError as error:
        return jsonify({"success": False, "error": str(error), "data": [], "props": []}), 503
    except (requests.RequestException, ProviderRequestError):
        return jsonify({"success": False, "error": "The Odds API live props request is unavailable right now.", "data": [], "props": []}), 502
