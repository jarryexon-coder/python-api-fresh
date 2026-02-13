#!/usr/bin/env python3
"""
Fetch NHL player season stats from SportsData.io and update the local JSON file.
Preserves custom fields (salary, ownership, etc.) not provided by the API.
"""

import os
import json
import requests
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
API_KEY = os.getenv("SPORTSDATA_NHL_API_KEY")
if not API_KEY:
    raise ValueError("❌ SPORTSDATA_NHL_API_KEY environment variable not set.")

SEASON = "2026"  # adjust as needed (e.g., "2025" for completed season)
PLAYERS_FILE = Path(__file__).parent.parent / "data" / "nhl_players_data_comprehensive_fixed.json"
# If file is in root, adjust:
if not PLAYERS_FILE.exists():
    PLAYERS_FILE = Path(__file__).parent.parent / "nhl_players_data_comprehensive_fixed.json"

PLAYER_STATS_URL = f"https://api.sportsdata.io/v3/nhl/stats/json/PlayerSeasonStats/{SEASON}"
HEADERS = {"Ocp-Apim-Subscription-Key": API_KEY}

# ----------------------------------------------------------------------
# Name normalization (same as NBA script)
# ----------------------------------------------------------------------
def normalize_name(name):
    if not name:
        return ""
    nfkd_form = unicodedata.normalize('NFKD', name)
    only_ascii = nfkd_form.encode('ASCII', 'ignore').decode('utf-8')
    only_ascii = re.sub(r'\b(Jr|Sr|I{1,3}|IV|V|VI?)\b\.?', '', only_ascii, flags=re.IGNORECASE)
    only_ascii = re.sub(r'[^\w\s-]', '', only_ascii)
    only_ascii = re.sub(r'\s+', ' ', only_ascii).strip().lower()
    return only_ascii

# ----------------------------------------------------------------------
# Load existing players
# ----------------------------------------------------------------------
print(f"📂 Loading existing players from {PLAYERS_FILE}...")
if not PLAYERS_FILE.exists():
    raise FileNotFoundError(f"NHL players file not found at {PLAYERS_FILE}")

with open(PLAYERS_FILE, "r") as f:
    existing_players = json.load(f)
print(f"✅ Loaded {len(existing_players)} players.")

# ----------------------------------------------------------------------
# Fetch API data
# ----------------------------------------------------------------------
print(f"🌐 Fetching player stats from SportsData.io (season {SEASON})...")
response = requests.get(PLAYER_STATS_URL, headers=HEADERS)
if response.status_code != 200:
    raise Exception(f"API request failed: {response.status_code} - {response.text}")

api_players = response.json()
print(f"✅ Received {len(api_players)} players from API.")

# Build lookup with normalized names
api_lookup = {}
for p in api_players:
    norm = normalize_name(p["Name"])
    api_lookup[norm] = p

# ----------------------------------------------------------------------
# Update existing players with API data
# ----------------------------------------------------------------------
updated_count = 0
not_found = []

for player in existing_players:
    name = player.get("name") or player.get("playerName")
    if not name:
        continue

    norm_player = normalize_name(name)
    api_player = api_lookup.get(norm_player)

    if api_player:
        # Map NHL stats (adjust field names as needed)
        # Common NHL stats from SportsData:
        # - Goals, Assists, Points, PlusMinus, PenaltyMinutes, Shots, etc.
        player["points"] = api_player.get("Points", player.get("points", 0))
        player["goals"] = api_player.get("Goals", player.get("goals", 0))
        player["assists"] = api_player.get("Assists", player.get("assists", 0))
        player["plusMinus"] = api_player.get("PlusMinus", player.get("plusMinus", 0))
        player["penaltyMinutes"] = api_player.get("PenaltyMinutes", player.get("penaltyMinutes", 0))
        player["shots"] = api_player.get("Shots", player.get("shots", 0))
        player["gamesPlayed"] = api_player.get("Games", player.get("gamesPlayed", 0))

        # Fantasy points (if available)
        fantasy_pts = api_player.get("FantasyPoints", api_player.get("FantasyPointsFanDuel", 0))
        player["projection"] = fantasy_pts
        player["projFP"] = fantasy_pts
        player["fantasyScore"] = fantasy_pts
        player["fp"] = fantasy_pts

        # Confidence / accuracy (set defaults, not from API)
        player["projectionConfidence"] = 75
        player["accuracy"] = 90
        player["outcome"] = "correct"
        player["actual_result"] = "Updated via SportsData.io"

        # Team and position
        player["team"] = api_player.get("Team", player.get("team", ""))
        player["teamAbbrev"] = player["team"]
        player["position"] = api_player.get("Position", player.get("position", ""))
        player["pos"] = player["position"]

        # Minutes projected – NHL API may not provide this; keep existing or set 0
        player["minutesProjected"] = player.get("minutesProjected", 0)

        # Injury status – keep existing or set default
        if "injuryStatus" not in player or not player["injuryStatus"]:
            player["injuryStatus"] = "healthy"
        player["trend"] = "stable"

        # Timestamp
        player["lastUpdated"] = datetime.utcnow().isoformat() + "Z"
        player["is_real_data"] = True

        updated_count += 1
    else:
        not_found.append(name)

print(f"✅ Updated stats for {updated_count} players.")
if not_found:
    print(f"⚠️  {len(not_found)} players not found in API (kept original data):")
    unique_not_found = list(dict.fromkeys(not_found))
    for name in unique_not_found[:15]:
        print(f"   - {name}")
    if len(unique_not_found) > 15:
        print(f"   ... and {len(unique_not_found)-15} more.")

# ----------------------------------------------------------------------
# Save updated file
# ----------------------------------------------------------------------
with open(PLAYERS_FILE, "w") as f:
    json.dump(existing_players, f, indent=2)

print(f"💾 Saved updated data to {PLAYERS_FILE}")
