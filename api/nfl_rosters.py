"""Live NFL roster access with a local fallback for provider outages."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests
from flask import Blueprint, jsonify, request


nfl_rosters_bp = Blueprint("nfl_rosters", __name__, url_prefix="/api/nfl")
BDL_NFL_URL = "https://api.balldontlie.io/nfl/v1/players/active"
FALLBACK_PATH = Path(__file__).resolve().parent.parent / "nfl_roster_fallback.json"
_cache: tuple[float, list[dict[str, Any]], str] | None = None


def _normalise(player: dict[str, Any]) -> dict[str, Any]:
    team = player.get("team") if isinstance(player.get("team"), dict) else {}
    name = player.get("full_name") or " ".join(filter(None, [player.get("first_name"), player.get("last_name")]))
    return {
        "id": str(player.get("id") or ""),
        "name": name or "Unknown player",
        "team": team.get("abbreviation") or "FA",
        "team_name": team.get("full_name") or team.get("name") or "Free agent",
        "position": player.get("position_abbreviation") or player.get("position") or "—",
        "jersey_number": player.get("jersey_number"),
        "college": player.get("college"),
        "experience": player.get("experience"),
        "age": player.get("age"),
        "active": True,
    }


def _local_fallback() -> list[dict[str, Any]]:
    if not FALLBACK_PATH.exists():
        return []
    try:
        payload = json.loads(FALLBACK_PATH.read_text(encoding="utf-8"))
        return [_normalise(player) for player in payload if isinstance(player, dict)] if isinstance(payload, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def active_roster() -> tuple[list[dict[str, Any]], str]:
    """Return all active NFL players, caching the provider response for six hours."""
    global _cache
    if _cache and time.time() - _cache[0] < 6 * 60 * 60:
        return _cache[1], _cache[2]
    key = os.getenv("BALLDONTLIE_API_KEY")
    if key:
        try:
            rows: list[dict[str, Any]] = []
            cursor: Any = None
            for _ in range(40):
                params: dict[str, Any] = {"per_page": 100}
                if cursor is not None:
                    params["cursor"] = cursor
                response = requests.get(BDL_NFL_URL, headers={"Authorization": key, "Accept": "application/json"}, params=params, timeout=15)
                response.raise_for_status()
                payload = response.json()
                page = payload.get("data", []) if isinstance(payload, dict) else []
                rows.extend(_normalise(player) for player in page if isinstance(player, dict))
                cursor = payload.get("meta", {}).get("next_cursor") if isinstance(payload, dict) else None
                if not cursor or not page:
                    break
            if rows:
                _cache = (time.time(), rows, "BallDontLie NFL active players")
                return rows, _cache[2]
        except requests.RequestException:
            pass
    rows = _local_fallback()
    source = "Local NFL roster fallback" if rows else "No roster source available"
    _cache = (time.time(), rows, source)
    return rows, source


@nfl_rosters_bp.get("/rosters")
def rosters():
    team_filter = request.args.get("team", "").upper()
    rows, source = active_roster()
    if team_filter:
        rows = [row for row in rows if row["team"] == team_filter]
    teams: dict[str, list[dict[str, Any]]] = {}
    for player in rows:
        teams.setdefault(player["team"], []).append(player)
    for team_rows in teams.values():
        team_rows.sort(key=lambda player: (player["position"], player["name"]))
    return jsonify({"success": True, "source": source, "updated_at": int(time.time()), "count": len(rows), "teams": teams, "data": rows})


@nfl_rosters_bp.get("/players/active")
def players():
    limit = min(max(request.args.get("limit", 200, type=int), 1), 5000)
    rows, source = active_roster()
    return jsonify({"success": True, "source": source, "count": len(rows), "data": rows[:limit]})
