"""Major League Baseball cards backed by BallDontLie and Tank01."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import requests
from flask import Blueprint, jsonify, request

mlb_bp = Blueprint("mlb", __name__, url_prefix="/api/mlb")
BDL_BASE_URL = "https://api.balldontlie.io"


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "body", "players", "props", "results", "response"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def _number(source: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        try:
            value = source.get(key)
            if value not in (None, ""):
                return float(value)
        except (TypeError, ValueError):
            pass
    return None


def _season() -> int:
    return request.args.get("season", type=int) or int(os.getenv("MLB_DEFAULT_SEASON", datetime.now().year))


def _bdl_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    key = os.getenv("BALLDONTLIE_API_KEY")
    if not key:
        raise RuntimeError("BALLDONTLIE_API_KEY is not configured in Railway Variables.")
    response = requests.get(f"{BDL_BASE_URL}{path}", headers={"Authorization": key, "Accept": "application/json"}, params=params, timeout=15)
    response.raise_for_status()
    return response.json()


def _player_name(row: dict[str, Any]) -> tuple[dict[str, Any], str]:
    player = row.get("player") if isinstance(row.get("player"), dict) else row
    full_name = " ".join(filter(None, [str(player.get("first_name") or ""), str(player.get("last_name") or "")])).strip()
    return player, full_name or str(player.get("name") or "Unknown player")


def _player_card(row: dict[str, Any], index: int) -> dict[str, Any]:
    player, name = _player_name(row)
    team = row.get("team") if isinstance(row.get("team"), dict) else {}
    games = _number(row, "batting_gp", "pitching_gp", "gp") or 0
    stats = {
        "hits": _number(row, "batting_h", "hits"), "runs": _number(row, "batting_r", "runs"),
        "rbis": _number(row, "batting_rbi", "rbi"), "home_runs": _number(row, "batting_hr", "home_runs"),
        "strikeouts": _number(row, "pitching_k", "strikeouts", "k"), "batting_average": _number(row, "batting_avg", "avg"),
        "era": _number(row, "pitching_era", "era"),
    }
    # Per-game projections are intentionally transparent and derive from the live season totals.
    projections = {key: round((value / games) * 1.02, 2) if value is not None and games else None for key, value in stats.items() if key not in {"batting_average", "era"}}
    return {
        "id": str(player.get("id") or row.get("player_id") or index), "name": name,
        "team": team.get("abbreviation") or team.get("name") or row.get("team_name") or "",
        "position": player.get("position") or row.get("position") or "", "games_played": games,
        "stats": {key: value for key, value in stats.items() if value is not None},
        "projections": {key: value for key, value in projections.items() if value is not None},
    }


@mlb_bp.get("/players")
def players():
    view = request.args.get("view", "stats").lower()
    if view not in {"stats", "projections", "props"}:
        return jsonify({"success": False, "error": "view must be stats, projections, or props"}), 400
    limit = min(max(request.args.get("limit", 50, type=int), 1), 100)
    try:
        if view == "props":
            url = os.getenv("TANK01_MLB_RAPIDAPI_URL")
            key = os.getenv("RAPIDAPI_KEY_TANK01") or os.getenv("RAPIDAPI_KEY")
            if not url or not key:
                return jsonify({"success": True, "source": "Tank01", "message": "Configure TANK01_MLB_RAPIDAPI_URL and RAPIDAPI_KEY_TANK01 for live MLB props.", "data": [], "count": 0})
            headers = {"X-RapidAPI-Key": key, "Accept": "application/json"}
            if host := os.getenv("TANK01_MLB_RAPIDAPI_HOST"):
                headers["X-RapidAPI-Host"] = host
            response = requests.get(url, headers=headers, params={"limit": limit}, timeout=15)
            response.raise_for_status()
            data = []
            for index, row in enumerate(_rows(response.json())):
                player = row.get("player") if isinstance(row.get("player"), dict) else row
                line = _number(row, "line", "line_value", "value", "overUnder")
                projection = _number(row, "projection", "projected", "projected_value")
                data.append({"id": str(row.get("id") or index), "name": player.get("name") or row.get("playerName") or row.get("player") or "Unknown player", "team": row.get("team") or row.get("teamAbv") or "", "market": row.get("stat") or row.get("propType") or row.get("market") or "MLB prop", "line": line, "projection": projection, "edge": round(((projection - line) / line) * 100, 1) if projection is not None and line not in (None, 0) else None, "odds": row.get("odds") or row.get("overOdds")})
            return jsonify({"success": True, "source": "Tank01 MLB", "is_real_data": True, "data": data, "count": len(data)})

        payload = _bdl_get("/mlb/v1/season_stats", {"season": _season(), "per_page": limit, "sort_by": "batting_hr", "sort_order": "desc"})
        data = [_player_card(row, index) for index, row in enumerate(_rows(payload))]
        return jsonify({"success": True, "source": "BallDontLie MLB season stats", "season": _season(), "view": view, "is_real_data": True, "data": data, "count": len(data)})
    except RuntimeError as error:
        return jsonify({"success": False, "error": str(error)}), 503
    except requests.RequestException as error:
        return jsonify({"success": False, "error": f"MLB provider request failed: {error}"}), 502


@mlb_bp.get("/teams/stats")
def team_stats():
    limit = min(max(request.args.get("limit", 50, type=int), 1), 100)
    try:
        payload = _bdl_get("/mlb/v1/teams/season_stats", {"season": _season(), "per_page": limit})
        data = []
        for index, row in enumerate(_rows(payload)):
            team = row.get("team") if isinstance(row.get("team"), dict) else {}
            data.append({"id": str(team.get("id") or index), "team": team.get("abbreviation") or row.get("team_name") or team.get("name") or "Unknown team", "name": team.get("display_name") or row.get("team_name") or team.get("name") or "Unknown team", "record": f"{row.get('pitching_w', 0)}-{row.get('pitching_l', 0)}", "stats": {"runs": _number(row, "batting_r"), "hits": _number(row, "batting_h"), "home_runs": _number(row, "batting_hr"), "rbis": _number(row, "batting_rbi"), "strikeouts": _number(row, "pitching_k"), "era": _number(row, "pitching_era"), "batting_average": _number(row, "batting_avg")}})
        return jsonify({"success": True, "source": "BallDontLie MLB team season stats", "season": _season(), "data": data, "count": len(data)})
    except RuntimeError as error:
        return jsonify({"success": False, "error": str(error)}), 503
    except requests.RequestException as error:
        return jsonify({"success": False, "error": f"MLB provider request failed: {error}"}), 502
