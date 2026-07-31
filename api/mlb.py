"""Major League Baseball cards backed by BallDontLie and Tank01."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import requests
from flask import Blueprint, jsonify, request

mlb_bp = Blueprint("mlb", __name__, url_prefix="/api/mlb")
BDL_BASE_URL = "https://api.balldontlie.io"
TANK01_MLB_HOST = "tank01-mlb-live-in-game-real-time-statistics.p.rapidapi.com"


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


@mlb_bp.get("/news")
def news():
    """Latest MLB news from Tank01, normalized for SportsWire and NewsDesk."""
    key = os.getenv("RAPIDAPI_KEY_TANK01") or os.getenv("RAPIDAPI_KEY")
    if not key:
        return jsonify({"success": False, "error": "RAPIDAPI_KEY_TANK01 or RAPIDAPI_KEY is not configured in Railway Variables."}), 503
    limit = min(max(request.args.get("limit", 10, type=int), 1), 50)
    try:
        response = requests.get(
            f"https://{TANK01_MLB_HOST}/getMLBNews",
            headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": TANK01_MLB_HOST, "Accept": "application/json"},
            params={"recentNews": "true", "maxItems": limit}, timeout=15,
        )
        response.raise_for_status()
        data = []
        for index, item in enumerate(_rows(response.json())):
            data.append({"id": item.get("link") or f"tank01-mlb-news-{index}", "title": item.get("title") or "MLB update", "description": item.get("description") or "Tank01 MLB news", "url": item.get("link"), "image": item.get("image"), "sport": "mlb", "player_ids": item.get("playerIDs", [])})
        return jsonify({"success": True, "source": "Tank01 MLB Top News and Headlines", "data": data, "news": data, "count": len(data)})
    except requests.RequestException as error:
        return jsonify({"success": False, "error": f"Tank01 MLB news request failed: {error}"}), 502


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
        "era": _number(row, "pitching_era", "era"), "ops": _number(row, "batting_ops", "ops"),
        "obp": _number(row, "batting_obp", "obp"), "slugging": _number(row, "batting_slg", "slg"),
        "whip": _number(row, "pitching_whip", "whip"), "k_per_9": _number(row, "pitching_k_per_9", "k_per_9"),
    }
    # Transparent per-game model. It uses real season production plus context rates,
    # rather than claiming unavailable Statcast measures such as barrel% or xwOBA.
    ops = stats["ops"]
    batting_modifier = max(.88, min(1.12, 1 + .15 * (((ops or .720) - .720) / .720)))
    k9 = stats["k_per_9"]
    strikeout_modifier = max(.88, min(1.12, 1 + .10 * (((k9 or 8.5) - 8.5) / 8.5)))
    projections = {}
    for key in ("hits", "runs", "rbis", "home_runs", "strikeouts"):
        value = stats[key]
        modifier = strikeout_modifier if key == "strikeouts" else batting_modifier
        projections[key] = round((value / games) * modifier, 2) if value is not None and games else None
    return {
        "id": str(player.get("id") or row.get("player_id") or index), "name": name,
        "team": team.get("abbreviation") or team.get("name") or row.get("team_name") or "",
        "position": player.get("position") or row.get("position") or "", "games_played": games,
        "stats": {key: value for key, value in stats.items() if value is not None},
        "projections": {key: value for key, value in projections.items() if value is not None},
        "model": {
            "version": "mlb-season-context-v1", "batting_modifier": round(batting_modifier, 3),
            "strikeout_modifier": round(strikeout_modifier, 3), "statcast_metrics_available": False,
            "formula": "season stat per game × capped OPS or K/9 context modifier",
        },
    }


@mlb_bp.get("/players")
def players():
    view = request.args.get("view", "stats").lower()
    if view not in {"stats", "projections", "props"}:
        return jsonify({"success": False, "error": "view must be stats, projections, or props"}), 400
    limit = min(max(request.args.get("limit", 50, type=int), 1), 100)
    try:
        if view == "props":
            # Tank01 has live stats and fantasy projections but not player prop lines.
            # BallDontLie GOAT exposes the real MLB player-prop market per game.
            game_ids = [request.args["game_id"]] if request.args.get("game_id") else []
            if not game_ids:
                games = _rows(_bdl_get("/mlb/v1/games", {"dates[]": request.args.get("date", datetime.now().strftime("%Y-%m-%d")), "per_page": 100}))
                game_ids = [str(game.get("id")) for game in games if game.get("id") is not None]
            data = []
            for game_id in game_ids:
                payload = _bdl_get("/mlb/v1/odds/player_props", {"game_id": game_id})
                for index, row in enumerate(_rows(payload)):
                    player = row.get("player") if isinstance(row.get("player"), dict) else {}
                    market = row.get("market") if isinstance(row.get("market"), dict) else {}
                    line = _number(row, "line_value", "line", "value")
                    odds = market.get("over_odds") or market.get("odds")
                    data.append({"id": str(row.get("id") or f"{game_id}-{index}"), "name": player.get("full_name") or player.get("name") or f"Player {row.get('player_id', '')}", "team": (player.get("team") or {}).get("abbreviation", "") if isinstance(player.get("team"), dict) else "", "market": row.get("prop_type") or "MLB prop", "line": line, "projection": None, "edge": None, "odds": odds, "game_id": game_id, "vendor": row.get("vendor")})
                    if len(data) >= limit:
                        break
                if len(data) >= limit:
                    break
            return jsonify({"success": True, "source": "BallDontLie MLB player props", "is_real_data": True, "data": data, "count": len(data), "message": None if data else "No live MLB player props are currently posted for this date."})

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
