"""Team performance context and opponent-strength calculations."""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime
from typing import Any

import requests
from flask import Blueprint, jsonify, request

team_context_bp = Blueprint("team_context", __name__, url_prefix="/api/insights")
BDL_BASE_URL = "https://api.balldontlie.io"
SPORT_PATHS = {"nfl": "nfl", "ncaaf": "ncaaf", "ncaab": "ncaab"}


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [row for row in payload["data"] if isinstance(row, dict)]
    return []


def _team(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _team_id(team: dict[str, Any]) -> str:
    value = team.get("id") or team.get("team_id") or team.get("abbreviation") or team.get("name")
    return str(value) if value is not None else ""


def _team_name(team: dict[str, Any]) -> str:
    return str(team.get("full_name") or team.get("name") or team.get("abbreviation") or "Unknown team")


def _score(game: dict[str, Any], home: bool) -> float | None:
    keys = ("home_score", "home_team_score") if home else ("visitor_score", "away_score", "visitor_team_score")
    for key in keys:
        try:
            raw = game.get(key)
            if raw not in (None, ""):
                return float(raw)
        except (TypeError, ValueError):
            pass
    return None


def _request_games(sport: str, season: int) -> list[dict[str, Any]]:
    key = os.getenv("BALLDONTLIE_API_KEY")
    if not key:
        raise RuntimeError("BALLDONTLIE_API_KEY is not configured in Railway Variables.")
    response = requests.get(
        f"{BDL_BASE_URL}/{SPORT_PATHS[sport]}/v1/games",
        headers={"Authorization": key, "Accept": "application/json"},
        params={"seasons[]": season, "per_page": 100},
        timeout=15,
    )
    response.raise_for_status()
    return _rows(response.json())


@team_context_bp.get("/<sport>/opponent-strength")
def opponent_strength(sport: str):
    """Derive current opponent strength from completed BallDontLie games.

    ``team_id`` is optional: without it, the API returns a ranked league table.
    The response includes sample size so the client never mistakes a partial season
    (the provider's current 100-game page) for a complete historical schedule.
    """
    sport = sport.lower()
    if sport not in SPORT_PATHS:
        return jsonify({"success": False, "error": "sport must be nfl, ncaaf, or ncaab"}), 400
    # During an upcoming season providers may have schedules but no completed games.
    # Default to the latest completed season unless Railway explicitly overrides it.
    season = request.args.get("season", type=int) or int(os.getenv("OPPONENT_STRENGTH_SEASON", datetime.now().year - 1))
    try:
        games = _request_games(sport, season)
        records: dict[str, dict[str, Any]] = defaultdict(lambda: {"wins": 0, "losses": 0, "ties": 0, "opponents": []})
        names: dict[str, str] = {}
        completed = 0
        for game in games:
            home, visitor = _team(game.get("home_team")), _team(game.get("visitor_team") or game.get("away_team"))
            home_id, visitor_id = _team_id(home), _team_id(visitor)
            home_score, visitor_score = _score(game, True), _score(game, False)
            if not home_id or not visitor_id or home_score is None or visitor_score is None:
                continue
            # Ignore future games where providers pre-populate a 0-0 score.
            status = str(game.get("status") or "").lower()
            if home_score == visitor_score == 0 and any(word in status for word in ("scheduled", "preview", "postponed")):
                continue
            completed += 1
            names[home_id], names[visitor_id] = _team_name(home), _team_name(visitor)
            records[home_id]["opponents"].append(visitor_id)
            records[visitor_id]["opponents"].append(home_id)
            if home_score > visitor_score:
                records[home_id]["wins"] += 1; records[visitor_id]["losses"] += 1
            elif visitor_score > home_score:
                records[visitor_id]["wins"] += 1; records[home_id]["losses"] += 1
            else:
                records[home_id]["ties"] += 1; records[visitor_id]["ties"] += 1

        win_pct = {
            team_id: (record["wins"] + 0.5 * record["ties"]) / max(record["wins"] + record["losses"] + record["ties"], 1)
            for team_id, record in records.items()
        }
        table = []
        for team_id, record in records.items():
            opponents = record["opponents"]
            strength = sum(win_pct.get(opponent, 0.5) for opponent in opponents) / len(opponents) if opponents else 0
            table.append({
                "team_id": team_id, "team": names.get(team_id, team_id),
                "record": f"{record['wins']}-{record['losses']}" + (f"-{record['ties']}" if record["ties"] else ""),
                "win_percentage": round(win_pct[team_id], 3),
                "opponent_strength": round(strength, 3),
                "opponent_strength_label": "Tough" if strength >= .600 else "Favorable" if strength <= .400 else "Average",
                "games_sampled": len(opponents),
            })
        table.sort(key=lambda row: (row["opponent_strength"], row["win_percentage"]), reverse=True)
        team_id = request.args.get("team_id")
        data = [row for row in table if row["team_id"] == team_id] if team_id else table
        return jsonify({"success": True, "sport": sport, "season": season, "source": "BallDontLie game results", "games_sampled": completed, "data": data, "count": len(data)})
    except RuntimeError as error:
        return jsonify({"success": False, "error": str(error)}), 503
    except requests.RequestException:
        # Opponent strength enriches player data but should never prevent the
        # NCAA/NFL screens from rendering when a provider entitlement does not
        # include historical game results.
        return jsonify({
            "success": True,
            "sport": sport,
            "season": season,
            "source": "Opponent strength temporarily unavailable",
            "games_sampled": 0,
            "data": [],
            "count": 0,
            "warning": "Opponent-strength game data is not available from the current provider plan.",
        })


@team_context_bp.get("/<sport>/player-stats")
def player_stats(sport: str):
    """Normalized provider-backed season statistics for NFL, NCAAF and NCAAB."""
    sport = sport.lower()
    if sport not in SPORT_PATHS:
        return jsonify({"success": False, "error": "sport must be nfl, ncaaf, or ncaab"}), 400
    season = request.args.get("season", type=int) or int(os.getenv("SPORT_STATS_SEASON", datetime.now().year - 1))
    limit = min(max(request.args.get("limit", 50, type=int), 1), 100)
    key = os.getenv("BALLDONTLIE_API_KEY")
    if not key:
        return jsonify({"success": False, "error": "BALLDONTLIE_API_KEY is not configured in Railway Variables."}), 503
    try:
        season_path = "season_stats" if sport == "nfl" else "player_season_stats"
        response = requests.get(
            f"{BDL_BASE_URL}/{SPORT_PATHS[sport]}/v1/{season_path}",
            headers={"Authorization": key, "Accept": "application/json"},
            params={"season": season, "per_page": limit}, timeout=15,
        )
        response.raise_for_status()
        data = []
        for index, row in enumerate(_rows(response.json())):
            player, team = _team(row.get("player")), _team(row.get("team"))
            name = " ".join(filter(None, [str(player.get("first_name") or ""), str(player.get("last_name") or "")])).strip() or str(player.get("name") or "Unknown player")
            stats = {key: row.get(key) for key in ("pts", "reb", "ast", "passing_yards", "rushing_yards", "receiving_yards", "touchdowns") if row.get(key) is not None}
            data.append({"id": str(player.get("id") or row.get("player_id") or index), "name": name, "team": team.get("abbreviation") or team.get("name") or "", "position": player.get("position") or "", "stats": stats, **stats})
        return jsonify({"success": True, "sport": sport, "season": season, "source": "BallDontLie season stats", "data": data, "count": len(data)})
    except requests.RequestException as error:
        return jsonify({"success": False, "error": f"Player-stat provider request failed: {error}"}), 502
