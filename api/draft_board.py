"""Tank01-powered NFL/NBA fantasy draft board.

The feed stays server-side so the RapidAPI key never reaches Expo.  Tank01 IDs are
the join key across ADP, projections, DFS salaries, depth charts, and player lists.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

import requests
from flask import Blueprint, jsonify, request

from api.fantasypros import get_fantasypros_nfl_draft_intelligence


draft_board_bp = Blueprint("draft_board", __name__, url_prefix="/api/draft")
HOSTS = {
    "nfl": "tank01-nfl-live-in-game-real-time-statistics-nfl.p.rapidapi.com",
    "nba": "tank01-fantasy-stats.p.rapidapi.com",
}
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _body(payload: Any) -> dict[str, Any] | list[Any]:
    if not isinstance(payload, dict):
        return payload if isinstance(payload, list) else {}
    body = payload.get("body")
    return body if isinstance(body, (dict, list)) else payload


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [row for row in value.values() if isinstance(row, dict)]
    return []


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _fetch(host: str, path: str, params: dict[str, Any]) -> dict[str, Any] | list[Any]:
    key = os.getenv("RAPIDAPI_KEY_TANK01") or os.getenv("RAPIDAPI_KEY")
    if not key:
        raise RuntimeError("RAPIDAPI_KEY_TANK01 is not configured in Railway Variables.")
    response = requests.get(
        f"https://{host}{path}", headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": host, "Accept": "application/json"},
        params=params, timeout=20,
    )
    response.raise_for_status()
    return _body(response.json())


def _optional_fetch(host: str, path: str, params: dict[str, Any]) -> dict[str, Any] | list[Any]:
    """An unavailable daily DFS slate must not hide the ADP draft board."""
    try:
        return _fetch(host, path, params)
    except requests.RequestException:
        return {}


def _depth_by_player(payload: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for team in _rows(payload):
        depth_chart = team.get("depthChart") if isinstance(team.get("depthChart"), dict) else {}
        for players in depth_chart.values():
            for player in _rows(players):
                player_id = str(player.get("playerID") or "")
                if player_id:
                    result[player_id] = str(player.get("depthPosition") or "")
    return result


def _estimated_salary(projection: float | None, adp: float | None) -> int | None:
    """Clearly marked estimate for off-slate drafting when DFS salaries are absent."""
    if projection is not None:
        return max(3500, min(12000, int(round(3500 + projection * 180))))
    if adp is not None:
        return max(3500, min(11500, int(round(11000 - min(adp, 250) * 30))))
    return None


def _name_key(name: Any) -> str:
    return "".join(character for character in str(name or "").lower() if character.isalnum())


def _nfl_projection_params() -> dict[str, Any]:
    return {
        "week": os.getenv("TANK01_NFL_PROJECTION_WEEK", "1"),
        "archiveSeason": os.getenv("TANK01_NFL_PROJECTION_SEASON", str(datetime.now().year)), "itemFormat": "list",
        "twoPointConversions": 2, "passYards": ".04", "passAttempts": "-.5", "passTD": 4, "passCompletions": 1,
        "passInterceptions": -2, "pointsPerReception": 1, "carries": ".2", "rushYards": ".1", "rushTD": 6,
        "fumbles": -2, "receivingYards": ".1", "receivingTD": 6, "targets": ".1", "fgMade": 3, "fgMissed": -1, "xpMade": 1, "xpMissed": -1,
    }


def _board(sport: str, date: str | None) -> dict[str, Any]:
    host = HOSTS[sport]
    today = date or datetime.now().strftime("%Y%m%d")
    if sport == "nfl":
        player_payload = _fetch(host, "/getNFLPlayerList", {"all": "true"})
        player_rows = _rows(player_payload.get("players", []) if isinstance(player_payload, dict) else [])
        projection_payload = _optional_fetch(host, "/getNFLProjections", _nfl_projection_params())
        projections = _rows(projection_payload.get("playerProjections", {}) if isinstance(projection_payload, dict) else [])
        adp_payload = _fetch(host, "/getNFLADP", {"adpType": "halfPPR"})
        adp_rows = _rows(adp_payload.get("adpList", []) if isinstance(adp_payload, dict) else [])
        dfs_payload = _optional_fetch(host, "/getNFLDFS", {"date": today, "includeTeamDefense": "true"})
        dfs_rows = _rows(dfs_payload.get("draftkings", []) if isinstance(dfs_payload, dict) else [])
        depth_rows = _optional_fetch(host, "/getNFLDepthCharts", {})
    else:
        player_payload = _fetch(host, "/getNBAPlayerList", {})
        player_rows = _rows(player_payload)
        projection_payload = _optional_fetch(host, "/getNBAProjections", {"numOfDays": 7, "pts": 1, "reb": 1.25, "TOV": -1, "stl": 3, "blk": 3, "ast": 1.5, "mins": 0})
        projections = _rows(projection_payload.get("playerProjections", {}) if isinstance(projection_payload, dict) else [])
        adp_payload = _fetch(host, "/getNBAADP", {})
        adp_rows = _rows(adp_payload.get("adpList", []) if isinstance(adp_payload, dict) else [])
        dfs_payload = _optional_fetch(host, "/getNBADFS", {"date": today})
        dfs_rows = _rows(dfs_payload.get("draftkings", []) if isinstance(dfs_payload, dict) else [])
        depth_rows = _optional_fetch(host, "/getNBADepthCharts", {})

    player_by_id = {str(row.get("playerID")): row for row in player_rows if row.get("playerID")}
    projection_by_id = {str(row.get("playerID")): row for row in projections if row.get("playerID")}
    salary_by_id = {str(row.get("playerID")): row for row in dfs_rows if row.get("playerID")}
    depth_by_id = _depth_by_player(depth_rows)
    fantasy_positions = {"nfl": {"QB", "RB", "WR", "TE", "PK", "K", "DEF"}, "nba": {"PG", "SG", "SF", "PF", "C", "G", "F"}}[sport]

    fantasypros_by_name: dict[str, dict[str, Any]] = {}
    fantasypros_warning = None
    if sport == "nfl":
        try:
            fantasypros = get_fantasypros_nfl_draft_intelligence()
            fantasypros_by_name = {_name_key(player.get("name")): player for player in fantasypros.get("data", [])}
        except (RuntimeError, requests.RequestException) as error:
            fantasypros_warning = str(error)

    data = []
    for adp in adp_rows:
        player_id = str(adp.get("playerID") or "")
        profile = player_by_id.get(player_id, {})
        projection_row = projection_by_id.get(player_id, {})
        salary_row = salary_by_id.get(player_id, {})
        position = str(projection_row.get("pos") or profile.get("pos") or salary_row.get("pos") or "")
        if position not in fantasy_positions:
            continue
        name = profile.get("longName") or projection_row.get("longName") or adp.get("longName") or "Unknown player"
        fantasypros_player = fantasypros_by_name.get(_name_key(name), {})
        adp_value = _number(fantasypros_player.get("adp")) or _number(adp.get("overallADP"))
        projection = _number(fantasypros_player.get("projectedPoints")) or _number(projection_row.get("fantasyPoints"))
        if projection is None and isinstance(projection_row.get("fantasyPointsDefault"), dict):
            projection = _number(projection_row["fantasyPointsDefault"].get("halfPPR") or projection_row["fantasyPointsDefault"].get("PPR") or projection_row["fantasyPointsDefault"].get("standard"))
        salary = _number(salary_row.get("salary"))
        estimated = salary is None
        salary = salary or _estimated_salary(projection, adp_value)
        value = round((projection / salary) * 1000, 2) if projection is not None and salary else round(100 / adp_value, 2) if adp_value else None
        data.append({
            "playerId": f"tank-{sport}-{player_id}", "tankPlayerId": player_id,
            "name": name,
            "team": profile.get("team") or projection_row.get("team") or salary_row.get("team") or "FA", "position": position,
            "projectedPoints": projection, "adp": adp_value, "positionAdp": adp.get("posADP"), "salary": int(salary) if salary else None,
            "salarySource": "Tank01 DFS" if not estimated else "Draft estimate (no current DFS slate)", "valueScore": value,
            "depthPosition": depth_by_id.get(player_id),
            "expertRank": int(fantasypros_player.get("consensusRank") or adp_value or 999),
            "projectionSource": "FantasyPros consensus via Apify" if fantasypros_player.get("projectedPoints") is not None else "Tank01 fantasy projections" if projection is not None else "ADP ranking (projection not posted)",
            "fantasyPros": fantasypros_player or None,
        })
    data.sort(key=lambda player: (player["projectedPoints"] is None, -(player["projectedPoints"] or 0), player["adp"] or 999))
    return {
        "success": True,
        "source": "FantasyPros + Tank01" if fantasypros_by_name else "Tank01",
        "sport": sport,
        "date": today,
        "adp_date": adp_payload.get("adpDate") if isinstance(adp_payload, dict) else None,
        "data": data,
        "count": len(data),
        "warning": fantasypros_warning,
    }


@draft_board_bp.get("/board")
def board():
    sport = request.args.get("sport", "nfl").lower()
    if sport not in HOSTS:
        return jsonify({"success": False, "error": "sport must be nfl or nba"}), 400
    date = request.args.get("date")
    cache_key = f"{sport}:{date or 'today'}"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[0] < 30 * 60:
        return jsonify(cached[1])
    try:
        result = _board(sport, date)
        _cache[cache_key] = (time.time(), result)
        return jsonify(result)
    except RuntimeError as error:
        return jsonify({"success": False, "error": str(error)}), 503
    except requests.RequestException as error:
        return jsonify({"success": False, "error": f"Tank01 {sport.upper()} draft feed failed: {error}"}), 502
