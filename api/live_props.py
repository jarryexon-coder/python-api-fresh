"""Current player-prop lines from The Odds API.

This is intentionally a line feed, not a synthetic projection generator.  When
the provider has no market for a sport or date the client receives an empty
slate instead of fabricated player cards.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import requests
from flask import Blueprint, jsonify, request


live_props_bp = Blueprint("live_props", __name__, url_prefix="/api")
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_SECONDS = 60

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


def _key() -> str | None:
    return os.getenv("THE_ODDS_API_KEY") or os.getenv("ODDS_API_KEY") or os.getenv("THEODDS_API_KEY")


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _market_label(value: str) -> str:
    return value.replace("batter_", "").replace("pitcher_", "").replace("player_", "").replace("_", " ").title()


def _rows(sport: str) -> dict[str, Any]:
    key = _key()
    if not key:
        raise RuntimeError("THE_ODDS_API_KEY is not configured in Railway Variables.")
    sport_key = SPORT_KEYS[sport]
    response = requests.get(
        f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds",
        params={"apiKey": key, "regions": "us", "markets": MARKETS[sport], "oddsFormat": "american"},
        timeout=20,
    )
    response.raise_for_status()
    events = response.json()
    if not isinstance(events, list):
        events = []

    result: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        game = f"{event.get('away_team') or 'Away'} @ {event.get('home_team') or 'Home'}"
        for bookmaker in event.get("bookmakers", []):
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
                    result.append({
                        "id": f"{event.get('id', 'event')}:{bookmaker.get('key', 'book')}:{market_key}:{player}:{line}",
                        "player": player,
                        "team": "",
                        "market": _market_label(market_key),
                        "market_key": market_key,
                        "line": line,
                        "projection": None,
                        "projection_available": False,
                        "projection_source": "No provider projection available",
                        "over_odds": prices["over"],
                        "under_odds": prices["under"],
                        "odds": prices["over"],
                        "game": game,
                        "game_id": event.get("id"),
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
        "source": "The Odds API live player props",
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
    except requests.RequestException as error:
        return jsonify({"success": False, "error": f"The Odds API live props request failed: {error}", "data": [], "props": []}), 502
