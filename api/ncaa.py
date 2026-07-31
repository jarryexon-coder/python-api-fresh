"""Division I NCAA player data endpoints backed by configured RapidAPI feeds."""
from __future__ import annotations

import os
from typing import Any

import requests
from flask import Blueprint, jsonify, request

ncaa_bp = Blueprint("ncaa", __name__, url_prefix="/api/ncaa")

SPORTS = {"football", "basketball"}
VIEWS = {"stats", "projections", "props"}


def _setting(sport: str, view: str, suffix: str) -> str | None:
    prefix = "NCAAF" if sport == "football" else "NCAAB"
    return os.getenv(f"{prefix}_RAPIDAPI_{view.upper()}_{suffix}") or os.getenv(
        f"{prefix}_RAPIDAPI_{suffix}"
    )


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "players", "results", "response", "props", "items"):
        if isinstance(payload.get(key), list):
            return [item for item in payload[key] if isinstance(item, dict)]
    nested = payload.get("data")
    if isinstance(nested, dict):
        return _rows(nested)
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


def _normalize(item: dict[str, Any], sport: str, view: str, index: int) -> dict[str, Any]:
    player = item.get("player") if isinstance(item.get("player"), dict) else item
    team = item.get("team") if isinstance(item.get("team"), dict) else {}
    stats = item.get("stats") if isinstance(item.get("stats"), dict) else item
    first_name = _first(player, "first_name", "firstName")
    last_name = _first(player, "last_name", "lastName")
    name = _first(player, "name", "player_name", "display_name") or f"{first_name} {last_name}".strip() or "Unknown player"
    projection = _number(item, "projection", "projected", "projected_points", "fantasy_points")
    line = _number(item, "line", "line_value", "value")
    edge = _number(item, "edge", "projection_edge")
    if edge is None and projection is not None and line not in (None, 0):
        edge = round(((projection - line) / line) * 100, 1)
    return {
        "id": _first(item, "id", "player_id", default=f"{sport}-{view}-{index}"),
        "name": name,
        "team": _first(team, "abbreviation", "name", "display_name") or _first(item, "team", "team_name", "school", default="D-I"),
        "position": _first(player, "position", "pos") or _first(item, "position", "pos"),
        "division": "I",
        "sport": sport,
        "market": _first(item, "market", "stat", "prop_type", default="Player stat"),
        "line": line,
        "projection": projection,
        "edge": edge,
        "odds": _first(item, "odds", "price", "over_odds"),
        "stats": {
            "points": _number(stats, "points", "pts"),
            "rebounds": _number(stats, "rebounds", "reb"),
            "assists": _number(stats, "assists", "ast"),
            "passing_yards": _number(stats, "passing_yards", "pass_yds"),
            "rushing_yards": _number(stats, "rushing_yards", "rush_yds"),
            "receiving_yards": _number(stats, "receiving_yards", "rec_yds"),
        },
    }


@ncaa_bp.get("/<sport>/players")
def players(sport: str):
    sport = sport.lower()
    view = request.args.get("view", "stats").lower()
    if sport not in SPORTS or view not in VIEWS:
        return jsonify({"success": False, "error": "sport must be football or basketball and view must be stats, projections, or props"}), 400

    url = _setting(sport, view, "URL")
    api_key = os.getenv("RAPIDAPI_KEY_NCAA") or os.getenv("RAPIDAPI_KEY")
    if not url or not api_key:
        return jsonify({"success": False, "error": f"Configure {'NCAAF' if sport == 'football' else 'NCAAB'}_RAPIDAPI_{view.upper()}_URL and RAPIDAPI_KEY_NCAA in Railway Variables."}), 503

    host = _setting(sport, view, "HOST")
    headers = {"X-RapidAPI-Key": api_key, "Accept": "application/json"}
    if host:
        headers["X-RapidAPI-Host"] = host
    params = {"division": "1", "limit": min(max(request.args.get("limit", 50, type=int), 1), 100)}
    for key in ("team", "season", "date"):
        if request.args.get(key):
            params[key] = request.args[key]
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        normalized = [_normalize(row, sport, view, index) for index, row in enumerate(_rows(response.json()))]
        return jsonify({"success": True, "sport": sport, "view": view, "division": "I", "source": "RapidAPI", "is_real_data": True, "data": normalized, "count": len(normalized)})
    except requests.RequestException as error:
        return jsonify({"success": False, "error": f"NCAA provider request failed: {error}"}), 502
