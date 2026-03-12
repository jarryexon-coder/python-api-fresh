#!/usr/bin/env python3
import os
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("BALLDONTLIE_API_KEY")
if not API_KEY:
    print("❌ BALLDONTLIE_API_KEY not set in environment")
    exit(1)

BASE_URL = "https://api.balldontlie.io"
HEADERS = {"Authorization": API_KEY}


def fetch_all_players():
    all_players = []
    cursor = None
    per_page = 100
    max_pages = 100  # safety limit (should be more than enough)
    page_count = 0

    while page_count < max_pages:
        page_count += 1
        params = {"per_page": per_page}
        if cursor:
            params["cursor"] = cursor

        print(f"Fetching page {page_count} with cursor {cursor}...")
        try:
            resp = requests.get(
                f"{BASE_URL}/v1/players", headers=HEADERS, params=params, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            players = data.get("data", [])
            if not players:
                print("No more players.")
                break

            all_players.extend(players)
            print(f"   Got {len(players)} players, total: {len(all_players)}")

            # Get next cursor from meta
            meta = data.get("meta", {})
            next_cursor = meta.get("next_cursor")
            if not next_cursor:
                print("No next cursor – end of data.")
                break
            cursor = next_cursor

            time.sleep(0.2)  # be nice to the API
        except Exception as e:
            print(f"❌ Error: {e}")
            break

    # Build ID -> name mapping
    name_map = {}
    for p in all_players:
        pid = str(p["id"])
        first = p.get("first_name", "")
        last = p.get("last_name", "")
        name = f"{first} {last}".strip()
        name_map[pid] = name if name else f"Player {pid}"

    with open("player_names.json", "w") as f:
        json.dump(name_map, f, indent=2)

    print(f"✅ Saved {len(name_map)} unique player names to player_names.json")
    return name_map


if __name__ == "__main__":
    fetch_all_players()
