"""Server-side FantasyPros data import from scheduled Apify tasks.

The mobile client only receives normalized draft intelligence.  The Apify token
and task identifiers remain Railway environment variables.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import requests
from flask import Blueprint, jsonify, request


fantasypros_bp = Blueprint("fantasypros", __name__, url_prefix="/api/fantasy/nfl")
_CACHE_SECONDS = 60 * 60
_cache: tuple[float, dict[str, Any]] | None = None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _key(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def _task_id(variable: str) -> str | None:
    value = os.getenv(variable)
    if value:
        return value
    # The original saved task remains a useful one-task setup while the user
    # creates separate scheduled projection, ADP, and ranking tasks.
    if variable == "APIFY_FANTASYPROS_TASK_ID":
        return "jiyabug~fantasypros-nfl-projections-adp-rankings-scraper-task"
    return None


def _fetch_task_rows(task_id: str, token: str) -> list[dict[str, Any]]:
    encoded_task_id = quote(task_id, safe="~")
    response = requests.get(
        f"https://api.apify.com/v2/actor-tasks/{encoded_task_id}/runs/last/dataset/items",
        params={"token": token, "status": "SUCCEEDED", "clean": "true", "format": "json"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def _stats(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def get_fantasypros_nfl_draft_intelligence(force: bool = False) -> dict[str, Any]:
    """Get and merge the latest successful output from configured Apify tasks."""
    global _cache
    if not force and _cache and time.time() - _cache[0] < _CACHE_SECONDS:
        return _cache[1]

    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        raise RuntimeError("APIFY_API_TOKEN is not configured in Railway Variables.")

    configured = [
        ("APIFY_FANTASYPROS_PROJECTIONS_TASK_ID", "projections"),
        ("APIFY_FANTASYPROS_ADP_TASK_ID", "adp"),
        ("APIFY_FANTASYPROS_RANKINGS_TASK_ID", "rankings"),
    ]
    if not any(os.getenv(variable) for variable, _ in configured):
        configured = [("APIFY_FANTASYPROS_TASK_ID", "latest")]

    players: dict[str, dict[str, Any]] = {}
    loaded_types: set[str] = set()
    task_errors: list[str] = []
    for variable, expected_type in configured:
        task_id = _task_id(variable)
        if not task_id:
            continue
        try:
            rows = _fetch_task_rows(task_id, token)
        except requests.RequestException as error:
            task_errors.append(f"{expected_type}: {error}")
            continue

        for row in rows:
            name = row.get("player_name") or row.get("name")
            if not name:
                continue
            data_type = str(row.get("data_type") or expected_type).lower()
            key = _key(name)
            player = players.setdefault(
                key,
                {
                    "name": str(name),
                    "team": row.get("team") or "FA",
                    "position": row.get("position") or "",
                    "projectedPoints": None,
                    "projectedStats": {},
                    "adp": None,
                    "adpSource": None,
                    "consensusRank": None,
                    "bestRank": None,
                    "worstRank": None,
                    "rankStdDev": None,
                    "week": row.get("week"),
                },
            )
            player["team"] = row.get("team") or player["team"]
            player["position"] = row.get("position") or player["position"]
            player["week"] = row.get("week") if row.get("week") is not None else player["week"]
            if data_type == "projections":
                player["projectedPoints"] = _number(row.get("projected_points"))
                player["projectedStats"] = _stats(row.get("projected_stats"))
            elif data_type == "adp":
                player["adp"] = _number(row.get("adp"))
                player["adpSource"] = row.get("adp_source")
            elif data_type == "rankings":
                player["consensusRank"] = _number(row.get("consensus_rank"))
                player["bestRank"] = _number(row.get("best_rank"))
                player["worstRank"] = _number(row.get("worst_rank"))
                player["rankStdDev"] = _number(row.get("std_dev"))
            loaded_types.add(data_type)

    result = {
        "success": True,
        "source": "FantasyPros via Apify",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "loadedTypes": sorted(loaded_types),
        "data": sorted(
            players.values(),
            key=lambda player: (
                player["consensusRank"] is None,
                player["consensusRank"] or 9999,
                player["adp"] is None,
                player["adp"] or 9999,
            ),
        ),
        "count": len(players),
        "warnings": task_errors,
    }
    _cache = (time.time(), result)
    return result


@fantasypros_bp.get("/draft-intelligence")
def draft_intelligence():
    try:
        return jsonify(get_fantasypros_nfl_draft_intelligence(request.args.get("refresh") == "true"))
    except RuntimeError as error:
        return jsonify({"success": False, "error": str(error)}), 503
    except requests.RequestException as error:
        return jsonify({"success": False, "error": f"FantasyPros Apify feed failed: {error}"}), 502
