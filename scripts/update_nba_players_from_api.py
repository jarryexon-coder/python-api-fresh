#!/usr/bin/env python3
"""
Fetch NBA player season stats from SportsData.io and update the local JSON file.
Uses name normalization to match players even with Jr./Sr./III and diacritics.
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
API_KEY = os.getenv("SPORTSDATA_NBA_API_KEY")
if not API_KEY:
    raise ValueError("❌ SPORTSDATA_NBA_API_KEY environment variable not set.")

SEASON = "2026"
PLAYERS_FILE = Path(__file__).parent.parent / "players_data_comprehensive_fixed.json"
PLAYER_STATS_URL = f"https://api.sportsdata.io/v3/nba/stats/json/PlayerSeasonStats/{SEASON}"
HEADERS = {"Ocp-Apim-Subscription-Key": API_KEY}

# ----------------------------------------------------------------------
# Name normalization
# ----------------------------------------------------------------------
def normalize_name(name):
    """Remove accents, Jr./Sr./III, extra spaces, and convert to lowercase."""
    if not name:
        return ""
    # Normalize unicode (e.g., é -> e)
    nfkd_form = unicodedata.normalize('NFKD', name)
    only_ascii = nfkd_form.encode('ASCII', 'ignore').decode('utf-8')
    # Remove common suffixes (Jr., Sr., III, IV, etc.)
    only_ascii = re.sub(r'\b(Jr|Sr|I{1,3}|IV|V|VI?)\b\.?', '', only_ascii, flags=re.IGNORECASE)
    # Remove punctuation except hyphen
    only_ascii = re.sub(r'[^\w\s-]', '', only_ascii)
    # Collapse multiple spaces and trim
    only_ascii = re.sub(r'\s+', ' ', only_ascii).strip().lower()
    return only_ascii

# ----------------------------------------------------------------------
# Load existing players
# ----------------------------------------------------------------------
print(f"📂 Loading existing players from {PLAYERS_FILE}...")
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
    # If duplicates exist, keep the last one (or could collect list)
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
        # Update numeric stats
        player["points"] = api_player.get("Points", player.get("points", 0))
        player["rebounds"] = api_player.get("Rebounds", player.get("rebounds", 0))
        player["assists"] = api_player.get("Assists", player.get("assists", 0))
        player["steals"] = api_player.get("Steals", player.get("steals", 0))
        player["blocks"] = api_player.get("BlockedShots", player.get("blocks", 0))
        player["threePointers"] = api_player.get("ThreePointersMade", player.get("threePointers", 0))
        player["gamesPlayed"] = api_player.get("Games", player.get("gamesPlayed", 0))

        # Projection / fantasy points
        fantasy_pts = api_player.get("FantasyPoints", 0)
        player["projection"] = fantasy_pts
        player["projFP"] = fantasy_pts
        player["fantasyScore"] = fantasy_pts
        player["fp"] = fantasy_pts

        # Confidence / accuracy (not in API, set defaults)
        player["projectionConfidence"] = 75
        player["accuracy"] = 90
        player["outcome"] = "correct"
        player["actual_result"] = "Updated via SportsData.io"

        # Team and position
        player["team"] = api_player.get("Team", player.get("team", ""))
        player["teamAbbrev"] = player["team"]
        player["position"] = api_player.get("Position", player.get("position", ""))
        player["pos"] = player["position"]

        # Minutes projected
        player["minutesProjected"] = api_player.get("Minutes", player.get("minutesProjected", 0))

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
    # Show unique not found (in case of duplicates)
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
