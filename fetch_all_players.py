import requests
import json
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure retries
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))

all_players = []
page = 0
per_page = 100

while True:
    page += 1
    url = f"https://www.balldontlie.io/api/v1/players?page={page}&per_page={per_page}"
    print(f"Fetching page {page}...")

    try:
        resp = session.get(url, timeout=10)
        if resp.status_code != 200:
            print(f"⚠️ Page {page} returned status {resp.status_code}: {resp.text[:200]}")
            break

        data = resp.json()
        players = data.get('data', [])
        if not players:
            print("No more players.")
            break

        all_players.extend(players)
        print(f"   Page {page}: got {len(players)} players, total {len(all_players)}")

        # Respect rate limits – don't hammer the API
        time.sleep(0.2)

    except Exception as e:
        print(f"❌ Error on page {page}: {e}")
        break

# Build mapping id -> full name
name_map = {}
for p in all_players:
    pid = p['id']
    first = p.get('first_name', '')
    last = p.get('last_name', '')
    name_map[pid] = f"{first} {last}".strip() or f"Player {pid}"

with open('player_names.json', 'w') as f:
    json.dump(name_map, f, indent=2)

print(f"✅ Saved {len(name_map)} player names to player_names.json")
