"""Division I NCAA player data with BallDontLie as the primary provider."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import requests
from flask import Blueprint, jsonify, request

ncaa_bp = Blueprint("ncaa", __name__, url_prefix="/api/ncaa")
BDL_BASE_URL = "https://api.balldontlie.io"
SPORTS = {"football": "ncaaf", "basketball": "ncaab"}
VIEWS = {"stats", "projections", "props"}


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "players", "results", "response", "props", "items"):
            if isinstance(payload.get(key), list):
                return [item for item in payload[key] if isinstance(item, dict)]
    return []


def _first(source: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def _number(source: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        try:
            value = source.get(key)
            if value not in (None, ""):
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _season() -> int:
    return request.args.get("season", type=int) or int(
        os.getenv("NCAA_DEFAULT_SEASON", str(datetime.now().year - 1))
    )


def _bdl_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("BALLDONTLIE_API_KEY")
    if not api_key:
        raise RuntimeError("BALLDONTLIE_API_KEY is not configured in Railway Variables.")
    response = requests.get(
        f"{BDL_BASE_URL}{path}",
        headers={"Authorization": api_key, "Accept": "application/json"},
        params=params,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def _normalize(item: dict[str, Any], sport: str, view: str, index: int) -> dict[str, Any]:
    player = item.get("player") if isinstance(item.get("player"), dict) else item
    team = item.get("team") if isinstance(item.get("team"), dict) else {}
    first_name = _first(player, "first_name", "firstName")
    last_name = _first(player, "last_name", "lastName")
    name = _first(player, "name", "player_name", "display_name") or f"{first_name} {last_name}".strip() or "Unknown player"
    stats = {
        "points": _number(item, "pts", "points"),
        "rebounds": _number(item, "reb", "rebounds"),
        "assists": _number(item, "ast", "assists"),
        "passing_yards": _number(item, "passing_yards", "pass_yds"),
        "rushing_yards": _number(item, "rushing_yards", "rush_yds"),
        "receiving_yards": _number(item, "receiving_yards", "rec_yds"),
    }
    baseline = stats["points"] if sport == "basketball" else (
        stats["passing_yards"] or stats["rushing_yards"] or stats["receiving_yards"]
    )
    line = _number(item, "line", "line_value", "value")
    projection = _number(item, "projection", "projected", "projected_points")
    if projection is None and view == "projections" and baseline is not None:
        projection = round(baseline * 1.02, 1)
    edge = _number(item, "edge", "projection_edge")
    if edge is None and projection is not None and line not in (None, 0):
        edge = round(((projection - line) / line) * 100, 1)
    return {
        "id": _first(player, "id", "player_id", default=f"{sport}-{view}-{index}"),
        "name": name,
        "team": _first(team, "abbreviation", "name", "full_name") or _first(item, "team_name", "school", default="D-I"),
        "position": _first(player, "position", "pos") or _first(item, "position", "pos"),
        "division": "I",
        "sport": sport,
        "market": _first(item, "market", "stat", "prop_type", default="Model baseline"),
        "line": line,
        "projection": projection,
        "edge": edge,
        "odds": _first(item, "odds", "price", "over_odds"),
        "stats": stats,
    }


def _rapidapi_props(sport: str) -> tuple[list[dict[str, Any]], str] | None:
    prefix = "NCAAF" if sport == "football" else "NCAAB"
    url = os.getenv(f"{prefix}_RAPIDAPI_PROPS_URL")
    key = os.getenv("RAPIDAPI_KEY_NCAA") or os.getenv("RAPIDAPI_KEY")
    if not url or not key:
        return None
    headers = {"X-RapidAPI-Key": key, "Accept": "application/json"}
    host = os.getenv(f"{prefix}_RAPIDAPI_PROPS_HOST")
    if host:
        headers["X-RapidAPI-Host"] = host
    response = requests.get(url, headers=headers, params={"limit": 100}, timeout=15)
    response.raise_for_status()
    return _rows(response.json()), "RapidAPI"


@ncaa_bp.get("/<sport>/players")
def players(sport: str):
    sport = sport.lower()
    view = request.args.get("view", "stats").lower()
    if sport not in SPORTS or view not in VIEWS:
        return jsonify({"success": False, "error": "sport must be football or basketball and view must be stats, projections, or props"}), 400

    try:
        if view == "props":
            rapidapi_result = _rapidapi_props(sport)
            if rapidapi_result:
                rows, source = rapidapi_result
                data = [_normalize(row, sport, view, index) for index, row in enumerate(rows)]
                return jsonify({"success": True, "sport": sport, "view": view, "division": "I", "source": source, "is_real_data": True, "data": data, "count": len(data)})
            if sport == "football" and request.args.get("game_id"):
                payload = _bdl_get("/ncaaf/v1/odds/player_props/opening", {"game_id": request.args["game_id"]})
                data = [_normalize(row, sport, view, index) for index, row in enumerate(_rows(payload))]
                return jsonify({"success": True, "sport": sport, "view": view, "division": "I", "source": "BallDontLie opening props", "is_real_data": True, "data": data, "count": len(data)})
            message = "Configure NCAAB_RAPIDAPI_PROPS_URL for NCAA Basketball player props." if sport == "basketball" else "Pass game_id for BallDontLie NCAAF opening props or configure NCAAF_RAPIDAPI_PROPS_URL for live player props."
            return jsonify({"success": True, "sport": sport, "view": view, "division": "I", "source": "BallDontLie", "is_real_data": False, "message": message, "data": [], "count": 0})

        payload = _bdl_get(f"/{SPORTS[sport]}/v1/player_season_stats", {"season": _season(), "per_page": min(max(request.args.get("limit", 50, type=int), 1), 100)})
        data = [_normalize(row, sport, view, index) for index, row in enumerate(_rows(payload))]
        return jsonify({"success": True, "sport": sport, "view": view, "division": "I", "source": "BallDontLie", "is_real_data": True, "data": data, "count": len(data)})
    except RuntimeError as error:
        return jsonify({"success": False, "error": str(error)}), 503
    except requests.RequestException as error:
        return jsonify({"success": False, "error": f"NCAA provider request failed: {error}"}), 502
