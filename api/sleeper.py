"""Small, read-only adapter for Sleeper's public fantasy league API."""
from __future__ import annotations

import re
import time
from typing import Any

import requests
from flask import Blueprint, jsonify


sleeper_bp = Blueprint("sleeper", __name__, url_prefix="/api/sleeper")
SLEEPER_BASE_URL = "https://api.sleeper.app/v1"
_cache: dict[str, tuple[float, Any]] = {}


def _get(path: str, ttl: int = 60) -> Any:
    cached = _cache.get(path)
    if cached and time.time() - cached[0] < ttl:
        return cached[1]
    response = requests.get(f"{SLEEPER_BASE_URL}{path}", timeout=12)
    response.raise_for_status()
    payload = response.json()
    _cache[path] = (time.time(), payload)
    return payload


def _valid_league_id(league_id: str) -> bool:
    """Sleeper league IDs are currently URL-safe alphanumeric values."""
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{4,64}", league_id))


@sleeper_bp.get("/leagues/<league_id>/overview")
def league_overview(league_id: str):
    """League details, members, rosters, and drafts—without exposing player secrets."""
    if not _valid_league_id(league_id):
        return jsonify({"success": False, "error": "Invalid Sleeper league ID."}), 400
    try:
        league = _get(f"/league/{league_id}")
        users = _get(f"/league/{league_id}/users")
        rosters = _get(f"/league/{league_id}/rosters")
        drafts = _get(f"/league/{league_id}/drafts", ttl=300)

        user_by_id = {
            str(user.get("user_id")): user
            for user in users if isinstance(user, dict) and user.get("user_id")
        }
        roster_rows = []
        for roster in rosters if isinstance(rosters, list) else []:
            if not isinstance(roster, dict):
                continue
            owner = user_by_id.get(str(roster.get("owner_id")), {})
            metadata = owner.get("metadata") if isinstance(owner.get("metadata"), dict) else {}
            display_name = (
                owner.get("display_name")
                or metadata.get("team_name")
                or "Unassigned roster"
            )
            player_ids = roster.get("players") if isinstance(roster.get("players"), list) else []
            starters = roster.get("starters") if isinstance(roster.get("starters"), list) else []
            roster_rows.append({
                "id": str(roster.get("roster_id") or roster.get("owner_id") or len(roster_rows) + 1),
                "owner": display_name,
                "owner_id": str(roster.get("owner_id") or ""),
                "players": [str(player_id) for player_id in player_ids],
                "player_count": len(player_ids),
                "starter_count": len([player_id for player_id in starters if player_id not in (None, "0")]),
                "wins": roster.get("settings", {}).get("wins", 0) if isinstance(roster.get("settings"), dict) else 0,
                "losses": roster.get("settings", {}).get("losses", 0) if isinstance(roster.get("settings"), dict) else 0,
            })

        return jsonify({
            "success": True,
            "source": "Sleeper public league API",
            "league": {
                "id": str(league.get("league_id") or league_id),
                "name": league.get("name") or "Sleeper league",
                "sport": league.get("sport"),
                "season": league.get("season"),
                "status": league.get("status"),
                "total_rosters": league.get("total_rosters") or len(roster_rows),
                "scoring_settings": league.get("scoring_settings") if isinstance(league.get("scoring_settings"), dict) else {},
            },
            "members": [
                {"id": str(user.get("user_id")), "name": user.get("display_name") or "League member"}
                for user in users if isinstance(user, dict)
            ],
            "rosters": roster_rows,
            "drafts": [
                {"id": str(draft.get("draft_id") or ""), "status": draft.get("status"), "type": draft.get("type"), "season": draft.get("season")}
                for draft in drafts if isinstance(draft, dict)
            ],
        })
    except requests.RequestException as error:
        return jsonify({"success": False, "error": f"Sleeper league request failed: {error}"}), 502
