"""
Balldontlie API fetchers for NBA data.
Reads API key from environment variable BALLDONTLIE_API_KEY.
All prints use flush=True to ensure logs appear immediately in Railway.
"""

import os
import time
import requests
from datetime import datetime
from typing import Optional, List, Dict

# ========== INTERNAL CACHE SETUP ==========
_cache = {}
CACHE_TTL_BALLDONTLIE = {
    'props': 300,
    'trends': 3600,
    'player_details': 3600,
    'lineup': 300,
    'injuries': 3600,
    'odds': 300,
    'games': 300,
    'season_avgs': 3600,
    'recent_stats': 300,
    'player_info': 3600,
    'active_players': 3600,
}

def get_cached(key):
    entry = _cache.get(key)
    if entry and time.time() - entry['timestamp'] < CACHE_TTL_BALLDONTLIE.get(key.split(':')[0], 300):
        return entry['data']
    return None

def set_cache(key, data):
    _cache[key] = {'data': data, 'timestamp': time.time()}

# ========== BALLDONTLIE API CONFIGURATION ==========
print("🔧 balldontlie_fetchers.py loaded", flush=True)
BALLDONTLIE_API_KEY = os.environ.get('BALLDONTLIE_API_KEY')
if not BALLDONTLIE_API_KEY:
    print("❌ BALLDONTLIE_FETCHERS: BALLDONTLIE_API_KEY not set in environment", flush=True)
else:
    print(f"🔑 BALLDONTLIE_FETCHERS: Key loaded (starts with {BALLDONTLIE_API_KEY[:8]}...)", flush=True)

BALLDONTLIE_BASE_URL = "https://api.balldontlie.io"
BALLDONTLIE_HEADERS = {"Authorization": BALLDONTLIE_API_KEY}

def make_request(endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """Generic request handler for Balldontlie API."""
    if not BALLDONTLIE_API_KEY:
        print("❌ BALLDONTLIE_API_KEY not set – cannot make request", flush=True)
        return None
    url = f"{BALLDONTLIE_BASE_URL}{endpoint}"
    try:
        print(f"📡 Making Balldontlie request to {endpoint}", flush=True)
        resp = requests.get(url, headers=BALLDONTLIE_HEADERS, params=params, timeout=10)
        print(f"📡 Response status: {resp.status_code}", flush=True)
        if resp.status_code != 200:
            print(f"⚠️ Response body: {resp.text[:500]}", flush=True)  # first 500 chars
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"⚠️ Balldontlie API error on {endpoint}: {e}", flush=True)
        return None

# ========== FETCHER FUNCTIONS ==========

def fetch_player_injuries(season: Optional[int] = None) -> Optional[List[Dict]]:
    cache_key = f"injuries:{season or 'current'}"
    cached = get_cached(cache_key)
    if cached:
        print("📦 Using cached injuries", flush=True)
        return cached
    params = {}
    if season:
        params['season'] = season
    response = make_request('/v1/player_injuries', params=params)
    if response and 'data' in response:
        injuries = response['data']
        set_cache(cache_key, injuries)
        return injuries
    return None

def fetch_player_props(player_id: Optional[int] = None, game_id: Optional[int] = None) -> Optional[List[Dict]]:
    cache_key = f"player_props:p{player_id or 'all'}:g{game_id or 'all'}"
    cached = get_cached(cache_key)
    if cached:
        print("📦 Using cached player props", flush=True)
        return cached
    params = {}
    if player_id:
        params['player_id'] = player_id
    if game_id:
        params['game_id'] = game_id
    response = make_request('/v2/odds/player_props', params=params)
    if response and 'data' in response:
        props = response['data']
        set_cache(cache_key, props)
        return props
    return None

def fetch_game_odds(game_id: Optional[int] = None) -> Optional[List[Dict]]:
    cache_key = f"odds:g{game_id or 'all'}"
    cached = get_cached(cache_key)
    if cached:
        print("📦 Using cached game odds", flush=True)
        return cached
    params = {}
    if game_id:
        params['game_id'] = game_id
    response = make_request('/v2/odds', params=params)
    if response and 'data' in response:
        odds = response['data']
        set_cache(cache_key, odds)
        return odds
    return None

def fetch_player_season_averages(player_ids: List[int], season: int = 2024) -> Optional[List[Dict]]:
    if not player_ids:
        return None
    ids_str = ','.join(str(pid) for pid in sorted(player_ids)[:50])
    cache_key = f"season_avgs:{season}:{ids_str}"
    cached = get_cached(cache_key)
    if cached:
        print("📦 Using cached season averages", flush=True)
        return cached
    params = {
        'season': season,
        'player_ids[]': player_ids[:50]
    }
    response = make_request('/v1/season_averages', params=params)
    if response and 'data' in response:
        avgs = response['data']
        set_cache(cache_key, avgs)
        return avgs
    return None

def fetch_player_recent_stats(player_id: int, per_page: int = 5) -> Optional[List[Dict]]:
    cache_key = f"recent_stats:{player_id}:{per_page}"
    cached = get_cached(cache_key)
    if cached:
        print("📦 Using cached recent stats", flush=True)
        return cached
    params = {
        'player_ids[]': player_id,
        'per_page': per_page,
        'order': 'desc'
    }
    response = make_request('/v1/stats', params=params)
    if response and 'data' in response:
        stats = response['data']
        set_cache(cache_key, stats)
        return stats
    return None

def fetch_player_info(player_id: int) -> Optional[Dict]:
    cache_key = f"player_info:{player_id}"
    cached = get_cached(cache_key)
    if cached:
        print("📦 Using cached player info", flush=True)
        return cached
    response = make_request(f'/v1/players/{player_id}')
    if response and 'data' in response:
        info = response['data']
        set_cache(cache_key, info)
        return info
    return None

def fetch_active_players(per_page: int = 100) -> Optional[List[Dict]]:
    cache_key = f"active_players:{per_page}"
    cached = get_cached(cache_key)
    if cached:
        print("📦 Using cached active players", flush=True)
        return cached
    print("📡 Calling fetch_active_players make_request", flush=True)
    response = make_request('/v1/players', params={'per_page': per_page})
    if response and 'data' in response:
        players = response['data']
        print(f"✅ Fetched {len(players)} active players from Balldontlie", flush=True)
        set_cache(cache_key, players)
        return players
    print("❌ fetch_active_players: No data or 'data' key missing", flush=True)
    return None

def fetch_todays_games(date: Optional[str] = None) -> Optional[List[Dict]]:
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    cache_key = f"games:{date}"
    cached = get_cached(cache_key)
    if cached:
        print("📦 Using cached today's games", flush=True)
        return cached
    response = make_request('/v1/games', params={'dates[]': date})
    if response and 'data' in response:
        games = response['data']
        set_cache(cache_key, games)
        return games
    return None

def fetch_odds_for_games(game_ids: List[int]) -> List[Dict]:
    if not game_ids:
        return []
    all_odds = []
    for gid in game_ids[:5]:
        odds = fetch_game_odds(gid)
        if odds:
            all_odds.extend(odds)
    return all_odds
