"""Major League Baseball cards backed by BallDontLie and Tank01."""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

import requests
from flask import Blueprint, jsonify, request

mlb_bp = Blueprint("mlb", __name__, url_prefix="/api/mlb")
BDL_BASE_URL = "https://api.balldontlie.io"
TANK01_MLB_HOST = "tank01-mlb-live-in-game-real-time-statistics.p.rapidapi.com"
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


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


def _cached_rows(key: str, path: str, params: dict[str, Any], ttl: int = 60) -> list[dict[str, Any]]:
    """Fetch every cursor page once, then reuse it for a short period."""
    force = request.args.get("force", "").lower() in {"1", "true", "yes"}
    cached = _cache.get(key)
    if not force and cached and time.time() - cached[0] < ttl:
        return cached[1]
    rows: list[dict[str, Any]] = []
    cursor: Any = None
    for _ in range(20):
        query = {**params, "per_page": 100}
        if cursor is not None:
            query["cursor"] = cursor
        payload = _bdl_get(path, query)
        page = _rows(payload)
        rows.extend(page)
        cursor = payload.get("meta", {}).get("next_cursor") if isinstance(payload, dict) else None
        if not cursor or not page:
            break
    _cache[key] = (time.time(), rows)
    return rows


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
            reported_at = item.get("publishedAt") or item.get("published_at") or item.get("date") or item.get("timestamp") or item.get("newsDate") or item.get("time")
            data.append({"id": item.get("link") or f"tank01-mlb-news-{index}", "title": item.get("title") or "MLB update", "description": item.get("description") or "Tank01 MLB news", "url": item.get("link"), "image": item.get("image"), "sport": "mlb", "player_ids": item.get("playerIDs", []), "reported_at": reported_at})
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
        "doubles": _number(row, "batting_2b", "doubles"), "total_bases": _number(row, "batting_tb", "total_bases"),
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
    for key in ("hits", "runs", "rbis", "home_runs", "doubles", "total_bases", "strikeouts"):
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


def _season_rows(season: int) -> list[dict[str, Any]]:
    return _cached_rows(f"player-season-{season}", "/mlb/v1/season_stats", {"season": season}, ttl=60)


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
            games_by_id: dict[str, dict[str, Any]] = {}
            game_ids = [request.args["game_id"]] if request.args.get("game_id") else []
            if not game_ids:
                games = _rows(_bdl_get("/mlb/v1/games", {"dates[]": request.args.get("date", datetime.now().strftime("%Y-%m-%d")), "per_page": 100}))
                game_ids = [str(game.get("id")) for game in games if game.get("id") is not None]
                games_by_id = {str(game.get("id")): game for game in games if game.get("id") is not None}
            active_players = {str(player.get("id")): player for player in _cached_rows("active-players", "/mlb/v1/players/active", {})}
            season_cards = {str((row.get("player") or {}).get("id")): _player_card(row, index) for index, row in enumerate(_season_rows(_season()))}
            data = []
            per_game_limit = max(1, limit // max(len(game_ids), 1))
            extra_slots = limit % max(len(game_ids), 1)
            for game_number, game_id in enumerate(game_ids):
                payload = _bdl_get("/mlb/v1/odds/player_props", {"game_id": game_id})
                game = games_by_id.get(str(game_id), {})
                away = game.get("away_team") if isinstance(game.get("away_team"), dict) else {}
                home = game.get("home_team") if isinstance(game.get("home_team"), dict) else {}
                game_label = f"{away.get('abbreviation', 'Away')} @ {home.get('abbreviation', 'Home')}"
                game_cap = per_game_limit + (1 if game_number < extra_slots else 0)
                for index, row in enumerate(_rows(payload)):
                    player = row.get("player") if isinstance(row.get("player"), dict) else {}
                    player_id = str(row.get("player_id") or player.get("id") or "")
                    player = player or active_players.get(player_id, {})
                    market = row.get("market") if isinstance(row.get("market"), dict) else {}
                    line = _number(row, "line_value", "line", "value")
                    odds = market.get("over_odds") or market.get("odds")
                    prop_type = str(row.get("prop_type") or "MLB prop").lower()
                    projection_key = {
                        "hits": "hits", "runs": "runs", "rbis": "rbis", "rbi": "rbis", "home_runs": "home_runs",
                        "first_home_run": "home_runs", "strikeouts": "strikeouts", "pitcher_strikeouts": "strikeouts",
                        "doubles": "doubles", "total_bases": "total_bases", "runs_scored": "runs",
                    }.get(prop_type)
                    projection = (season_cards.get(player_id, {}).get("projections", {}).get(projection_key) if projection_key else None)
                    season_card = season_cards.get(player_id, {})
                    provider_name = str(player.get("full_name") or player.get("name") or "")
                    name = season_card.get("name") if provider_name.lower().startswith("player ") else provider_name
                    edge = round(((projection - line) / line) * 100, 1) if projection is not None and line not in (None, 0) else None
                    data.append({"id": str(row.get("id") or f"{game_id}-{index}"), "name": name or f"Player {player_id or 'unknown'}", "team": (player.get("team") or {}).get("abbreviation", "") if isinstance(player.get("team"), dict) else season_card.get("team", ""), "market": prop_type.replace("_", " "), "line": line, "projection": projection, "edge": edge, "odds": odds, "game_id": game_id, "game": game_label, "date": game.get("date"), "vendor": row.get("vendor")})
                    if index + 1 >= game_cap:
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


@mlb_bp.get("/rosters")
def rosters():
    """Current active MLB roster, grouped by all 30 teams."""
    try:
        players = _cached_rows("active-players", "/mlb/v1/players/active", {})
        season_cards = {str((row.get("player") or {}).get("id")): _player_card(row, index) for index, row in enumerate(_season_rows(_season()))}
        grouped: dict[str, dict[str, Any]] = {}
        for player in players:
            team = player.get("team") if isinstance(player.get("team"), dict) else {}
            team_id = str(team.get("id") or "unassigned")
            roster = grouped.setdefault(team_id, {
                "id": team_id, "name": team.get("display_name") or team.get("name") or "Unassigned",
                "abbreviation": team.get("abbreviation") or "", "league": team.get("league") or "",
                "division": team.get("division") or "", "players": [],
            })
            season_card = season_cards.get(str(player.get("id")))
            roster["players"].append({
                "id": str(player.get("id")), "name": player.get("full_name") or " ".join(filter(None, [player.get("first_name"), player.get("last_name")])),
                "position": player.get("position") or "", "jersey": player.get("jersey") or "", "bats_throws": player.get("bats_throws") or "",
                "games_played": season_card.get("games_played") if season_card else 0,
                "stats": season_card.get("stats", {}) if season_card else {},
                "projections": season_card.get("projections", {}) if season_card else {},
            })
        data = sorted(grouped.values(), key=lambda team: team["name"])
        for team in data:
            team["players"].sort(key=lambda player: (player["position"], player["name"]))
        return jsonify({"success": True, "source": "BallDontLie active MLB players", "data": data, "count": len(data)})
    except RuntimeError as error:
        return jsonify({"success": False, "error": str(error)}), 503
    except requests.RequestException as error:
        return jsonify({"success": False, "error": f"MLB roster request failed: {error}"}), 502


def _team_projection(team_stats: dict[str, Any] | None, opponent_stats: dict[str, Any] | None) -> float | None:
    if not team_stats:
        return None
    games = _number(team_stats, "gp") or 0
    runs = _number(team_stats, "batting_r")
    if not games or runs is None:
        return None
    baseline = runs / games
    opponent_era = _number(opponent_stats or {}, "pitching_era")
    # A bounded opponent ERA adjustment; not a sportsbook line.
    adjustment = max(.88, min(1.12, 1 + ((opponent_era or 4.10) - 4.10) * .045))
    return round(baseline * adjustment, 1)


@mlb_bp.get("/matchups")
def matchups():
    """Today's real MLB schedule with transparent team and player projections."""
    game_date = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
    try:
        games = _rows(_bdl_get("/mlb/v1/games", {"dates[]": game_date, "per_page": 100, "season_type": "regular"}))
        season = _season()
        active_players = _cached_rows("active-players", "/mlb/v1/players/active", {})
        active_by_team: dict[str, list[dict[str, Any]]] = {}
        for player in active_players:
            team = player.get("team") if isinstance(player.get("team"), dict) else {}
            active_by_team.setdefault(str(team.get("id")), []).append(player)
        team_stats = _cached_rows(f"team-season-{season}", "/mlb/v1/teams/season_stats", {"season": season})
        stats_by_team = {str((row.get("team") or {}).get("id")): row for row in team_stats if isinstance(row.get("team"), dict)}
        season_cards = {str((row.get("player") or {}).get("id")): _player_card(row, index) for index, row in enumerate(_season_rows(season))}
        data = []
        for game in games:
            home = game.get("home_team") if isinstance(game.get("home_team"), dict) else {}
            away = game.get("away_team") if isinstance(game.get("away_team"), dict) else {}
            home_id, away_id = str(home.get("id")), str(away.get("id"))
            sides = []
            for team, opponent, team_id, opponent_id in ((away, home, away_id, home_id), (home, away, home_id, away_id)):
                roster = []
                for index, player in enumerate(active_by_team.get(team_id, [])):
                    card = season_cards.get(str(player.get("id")))
                    roster.append(card or {
                        "id": str(player.get("id")), "name": player.get("full_name") or "Unknown player", "team": team.get("abbreviation") or "",
                        "position": player.get("position") or "", "games_played": 0, "stats": {}, "projections": {},
                    })
                roster.sort(key=lambda player: (player["projections"].get("runs") or 0, player["projections"].get("rbis") or 0), reverse=True)
                sides.append({
                    "id": team_id, "name": team.get("display_name") or team.get("name") or "Team", "abbreviation": team.get("abbreviation") or "",
                    "projected_runs": _team_projection(stats_by_team.get(team_id), stats_by_team.get(opponent_id)),
                    "players": roster,
                })
            data.append({
                "id": str(game.get("id")), "date": game.get("date"), "status": game.get("status"), "venue": game.get("venue"),
                "away": sides[0], "home": sides[1], "projection_method": "Team runs per game × bounded opponent ERA adjustment; player values are current-season per-game OPS/K/9 adjusted projections.",
            })
        return jsonify({"success": True, "source": "BallDontLie MLB schedule and season statistics", "date": game_date, "data": data, "count": len(data)})
    except RuntimeError as error:
        return jsonify({"success": False, "error": str(error)}), 503
    except requests.RequestException as error:
        return jsonify({"success": False, "error": f"MLB matchup request failed: {error}"}), 502
