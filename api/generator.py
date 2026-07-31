"""Provider-backed generation endpoint used by mobile recommendation surfaces."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import requests
from flask import Blueprint, jsonify, request

generator_bp = Blueprint("generator", __name__, url_prefix="/api/generator")
BASE_URL = "https://api.balldontlie.io"
SUPPORTED_SPORTS = {"nba": "nba", "nfl": "nfl", "ncaaf": "ncaaf", "ncaab": "ncaab"}
SURFACES = {"predictions", "fantasy", "daily-picks", "prizepicks"}


def _rows(payload: Any) -> list[dict[str, Any]]:
    return [row for row in (payload.get("data", []) if isinstance(payload, dict) else []) if isinstance(row, dict)]


def _number(source: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        try:
            value = source.get(key)
            if value not in (None, ""):
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


@generator_bp.post("/generate")
def generate():
    """Generate transparent stat-based cards from live provider season data.

    This deliberately returns inputs, line, projection, and the simple adjustment;
    it is not presented as an undisclosed AI or sportsbook line.
    """
    payload = request.get_json(silent=True) or {}
    sport = str(payload.get("sport", "nfl")).lower()
    surface = str(payload.get("surface", "predictions")).lower()
    if sport not in SUPPORTED_SPORTS or surface not in SURFACES:
        return jsonify({"success": False, "error": "sport must be nba, nfl, ncaaf, or ncaab; surface must be predictions, fantasy, daily-picks, or prizepicks"}), 400
    api_key = os.getenv("BALLDONTLIE_API_KEY")
    if not api_key:
        return jsonify({"success": False, "error": "BALLDONTLIE_API_KEY is not configured in Railway Variables."}), 503
    count = min(max(int(payload.get("count", 8)), 1), 20)
    season = int(payload.get("season") or os.getenv("GENERATOR_DEFAULT_SEASON", datetime.now().year - 1))
    try:
        headers = {"Authorization": api_key, "Accept": "application/json"}
        players_by_id: dict[str, dict[str, Any]] = {}
        if sport == "nba":
            players_response = requests.get(f"{BASE_URL}/v1/players", headers=headers, params={"per_page": 100}, timeout=15)
            players_response.raise_for_status()
            players = _rows(players_response.json())
            players_by_id = {str(player.get("id")): player for player in players}
            response = requests.get(f"{BASE_URL}/v1/season_averages", headers=headers, params=[("season", season), *[("player_ids[]", player.get("id")) for player in players if player.get("id")]], timeout=15)
        else:
            response = requests.get(f"{BASE_URL}/{SUPPORTED_SPORTS[sport]}/v1/player_season_stats", headers=headers, params={"season": season, "per_page": 100}, timeout=15)
        response.raise_for_status()
        generated = []
        for index, row in enumerate(_rows(response.json())):
            player = row.get("player") if isinstance(row.get("player"), dict) else players_by_id.get(str(row.get("player_id")), row)
            team = row.get("team") if isinstance(row.get("team"), dict) else {}
            name = " ".join(str(player.get(key, "")).strip() for key in ("first_name", "last_name")).strip() or str(player.get("name") or "Unknown player")
            if sport in {"nba", "ncaab"}:
                market, baseline = "Points", _number(row, "pts", "points")
            else:
                options = [("Passing yards", _number(row, "passing_yards", "pass_yds")), ("Rushing yards", _number(row, "rushing_yards", "rush_yds")), ("Receiving yards", _number(row, "receiving_yards", "rec_yds"))]
                market, baseline = max(options, key=lambda option: option[1] or 0)
            if baseline is None or baseline <= 0:
                continue
            line = round(baseline * .98, 1)
            projection = round(baseline * 1.02, 1)
            edge = round(((projection - line) / line) * 100, 1) if line else 0
            generated.append({
                "id": f"{surface}-{sport}-{player.get('id', index)}", "player": name,
                "team": team.get("abbreviation") or team.get("name") or "D-I", "market": market,
                "line": line, "projection": projection, "edge": edge,
                "confidence": min(85, max(55, round(60 + abs(edge) * 4))),
                "reason": "Projection is a transparent 2% adjustment to the provider's current season baseline.",
            })
        generated.sort(key=lambda item: (item["confidence"], item["projection"]), reverse=True)
        return jsonify({"success": True, "surface": surface, "sport": sport, "season": season, "source": "BallDontLie player season stats", "generated_at": datetime.utcnow().isoformat() + "Z", "data": generated[:count], "count": min(count, len(generated))})
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "count and season must be valid numbers"}), 400
    except requests.RequestException as error:
        return jsonify({"success": False, "error": f"Generator provider request failed: {error}"}), 502
