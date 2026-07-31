"""Safe server-side Tank01 news proxies for SportsWire and NewsDesk."""
from __future__ import annotations

import os
from typing import Any

import requests
from flask import Blueprint, jsonify, request

tank_news_bp = Blueprint("tank_news", __name__, url_prefix="/api/tank")
SOURCES = {
    "nba": ("tank01-fantasy-stats.p.rapidapi.com", "/getNBANews", {"recentNews": "true"}),
    "nfl": ("tank01-nfl-live-in-game-real-time-statistics-nfl.p.rapidapi.com", "/getNFLNews", {"fantasyNews": "true"}),
}


def _items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return payload if isinstance(payload, list) else []
    for key in ("body", "data", "news", "articles"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


@tank_news_bp.get("/news/<sport>")
def news(sport: str):
    sport = sport.lower()
    if sport not in SOURCES:
        return jsonify({"success": False, "error": "sport must be nba or nfl"}), 400
    key = os.getenv("RAPIDAPI_KEY_TANK01") or os.getenv("RAPIDAPI_KEY")
    if not key:
        return jsonify({"success": False, "error": "RAPIDAPI_KEY_TANK01 or RAPIDAPI_KEY is not configured in Railway Variables."}), 503
    host, path, base_params = SOURCES[sport]
    limit = min(max(request.args.get("limit", 20, type=int), 1), 50)
    try:
        response = requests.get(
            f"https://{host}{path}",
            headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": host, "Accept": "application/json"},
            params={**base_params, "maxItems": limit}, timeout=15,
        )
        response.raise_for_status()
        data = []
        for index, item in enumerate(_items(response.json())):
            data.append({"id": item.get("link") or f"tank01-{sport}-news-{index}", "title": item.get("title") or "Sports update", "description": item.get("description") or f"Tank01 {sport.upper()} news", "url": item.get("link"), "image": item.get("image"), "sport": sport, "player_ids": item.get("playerIDs", [])})
        return jsonify({"success": True, "source": f"Tank01 {sport.upper()} Top News and Headlines", "data": data, "news": data, "count": len(data)})
    except requests.RequestException as error:
        return jsonify({"success": False, "error": f"Tank01 {sport.upper()} news request failed: {error}"}), 502
