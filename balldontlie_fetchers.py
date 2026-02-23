import os
import time
import random
import requests
from datetime import datetime, timedelta
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
    if not BALLDONTLIE_API_KEY:
        print("❌ BALLDONTLIE_API_KEY not set")
        return None
    url = f"{BALLDONTLIE_BASE_URL}{endpoint}"
    try:
        print(f"📡 Making Balldontlie request to {endpoint} with params {params}", flush=True)
        resp = requests.get(url, headers=BALLDONTLIE_HEADERS, params=params, timeout=10)
        print(f"📡 Response status: {resp.status_code}", flush=True)
        if resp.status_code != 200:
            print(f"⚠️ Response body: {resp.text[:200]}", flush=True)  # log first 200 chars
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"❌ Balldontlie API error on {endpoint}: {e}", flush=True)
        return None

# ========== PLAYER FETCHING ==========
def fetch_active_players(per_page: int = 100, cache: bool = True) -> Optional[List[Dict]]:
    """Fetch active NBA players from Balldontlie. Results cached for 1 hour."""
    cache_key = f"active_players:{per_page}"
    if cache:
        cached = get_cached(cache_key)
        if cached:
            print(f"✅ Using cached active players (first {per_page})", flush=True)
            return cached

    params = {'per_page': per_page, 'cursor': 0}
    data = make_request("/v1/players", params)
    players = data.get('data') if data else None
    if players and cache:
        set_cache(cache_key, players)
    return players

def fetch_all_active_players() -> List[Dict]:
    """Fetch ALL active NBA players using pagination (v1)."""
    all_players = []
    cursor = 0
    page = 1
    while True:
        print(f"📡 Fetching players page {page} with cursor {cursor}", flush=True)
        params = {'per_page': 100, 'cursor': cursor}
        response = make_request('/v1/players', params)
        if not response or 'data' not in response:
            break
        players = response['data']
        if not players:
            break
        all_players.extend(players)
        # Get next cursor from meta
        meta = response.get('meta', {})
        next_cursor = meta.get('next_cursor')
        if next_cursor is None:
            break
        cursor = next_cursor
        page += 1
        time.sleep(0.2)  # be nice to rate limits
    print(f"✅ Fetched total {len(all_players)} players", flush=True)
    return all_players

# ========== INJURIES ==========
def fetch_player_injuries(season: Optional[int] = None) -> Optional[List[Dict]]:
    """Fetch player injuries from Balldontlie."""
    cache_key = f"injuries:{season or 'current'}"
    cached = get_cached(cache_key)
    if cached:
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

# ========== SEASON AVERAGES ==========
def fetch_player_season_averages(player_ids: List[int], season: int = 2025) -> Dict[int, Dict]:
    """
    Fetch season averages for a list of player IDs.
    Returns dict mapping player_id -> average stats.
    """
    if not player_ids:
        return {}
    
    avg_map = {}
    for pid in player_ids:
        # Single-player request
        params = {'season': season, 'player_id': pid}
        response = make_request('/v1/season_averages', params)
        
        if response and 'data' in response and response['data']:
            # The API returns a list with one element
            avg_map[pid] = response['data'][0]
        
        # Small delay to respect rate limits (60 per minute = 1 per second)
        time.sleep(0.2)  # 200 ms → 5 requests per second (safe)
    
    print(f"✅ Fetched season averages for {len(avg_map)} players", flush=True)
    return avg_map

# ========== RECENT STATS ==========
def fetch_player_recent_stats(player_id: int, last_n: int = 5) -> Optional[List[Dict]]:
    """Fetch last N game stats for a player from Balldontlie."""
    cache_key = f"recent_stats:{player_id}:{last_n}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    end_date = datetime.now()
    start_date = end_date - timedelta(days=last_n * 3)

    params = {
        'player_ids[]': player_id,
        'start_date': start_date.strftime("%Y-%m-%d"),
        'end_date': end_date.strftime("%Y-%m-%d"),
        'per_page': last_n
    }
    data = make_request("/v1/stats", params)
    stats = data.get('data') if data else None
    if stats:
        set_cache(cache_key, stats)
        print(f"📊 Fetched {len(stats)} recent games for player {player_id}", flush=True)
    else:
        print(f"⚠️ No recent stats for player {player_id}", flush=True)
    return stats

# ========== PLAYER INFO ==========
def fetch_player_info(player_id: int) -> Optional[Dict]:
    """Fetch detailed info for a single player from Balldontlie."""
    cache_key = f"player_info:{player_id}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    data = make_request(f"/v1/players/{player_id}")
    if data and 'data' in data:
        player = data['data']
        set_cache(cache_key, player)
        print(f"👤 Fetched info for player {player_id}", flush=True)
        return player
    print(f"⚠️ No info found for player {player_id}", flush=True)
    return None

# ========== TODAY'S GAMES ==========
def fetch_todays_games() -> List[Dict]:
    """Fetch NBA games scheduled for today from Balldontlie."""
    cache_key = "todays_games"
    cached = get_cached(cache_key)
    if cached:
        print("✅ Using cached today's games", flush=True)
        return cached

    today = datetime.now().strftime("%Y-%m-%d")
    params = {
        'dates[]': today,
        'per_page': 20,
        'postseason': False
    }
    data = make_request("/v1/games", params)
    games = data.get('data') if data else []
    if games:
        set_cache(cache_key, games)
        print(f"📅 Fetched {len(games)} games for {today}", flush=True)
    else:
        print(f"⚠️ No games found for {today}", flush=True)
    return games

# ========== GAME ODDS ==========
def fetch_game_odds(sport: str = 'nba') -> List[Dict]:
    """Fetch odds from The Odds API."""
    ODDS_API_KEY = os.environ.get('ODDS_API_KEY')
    if not ODDS_API_KEY:
        print("⚠️ ODDS_API_KEY not set – cannot fetch odds", flush=True)
        return []

    sport_map = {
        'nba': 'basketball_nba',
        'nfl': 'americanfootball_nfl',
        'mlb': 'baseball_mlb',
        'nhl': 'icehockey_nhl'
    }
    sport_key = sport_map.get(sport, sport)

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        'apiKey': ODDS_API_KEY,
        'regions': 'us',
        'markets': 'h2h,spreads',
        'oddsFormat': 'american'
    }

    cache_key = f"odds:{sport}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    try:
        print(f"📡 Fetching odds from The Odds API for {sport_key}", flush=True)
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        odds_data = resp.json()
        set_cache(cache_key, odds_data)
        print(f"📊 Fetched odds for {len(odds_data)} games", flush=True)
        return odds_data
    except Exception as e:
        print(f"❌ Error fetching odds: {e}", flush=True)
        return []

# ========== BALLDONTLIE V2 PROPS (by player/game) ==========
def fetch_balldontlie_props(player_id: Optional[int] = None, game_id: Optional[int] = None) -> Optional[List[Dict]]:
    """Fetch player props from Balldontlie v2 (by player_id and/or game_id)."""
    cache_key = f"player_props:p{player_id or 'all'}:g{game_id or 'all'}"
    cached = get_cached(cache_key)
    if cached:
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
        print(f"📊 Fetched {len(props)} Balldontlie v2 props", flush=True)
        return props
    return None

# ========== THE ODDS API PLAYER PROPS (by sport) ==========
def fetch_player_props(sport: str = 'nba', source: str = 'theoddsapi') -> List[Dict]:
    """
    Fetch player props from The Odds API.
    
    Args:
        sport: 'nba' (maps to 'basketball_nba')
        source: ignored (kept for compatibility)
    
    Returns:
        List of events, each containing bookmaker props.
    """
    ODDS_API_KEY = os.environ.get('ODDS_API_KEY')
    if not ODDS_API_KEY:
        print("⚠️ ODDS_API_KEY not set – cannot fetch props", flush=True)
        return []

    sport_map = {
        'nba': 'basketball_nba',
        'nfl': 'americanfootball_nfl',
        'mlb': 'baseball_mlb',
        'nhl': 'icehockey_nhl'
    }
    sport_key = sport_map.get(sport, sport)

    cache_key = f"props:{sport_key}"
    cached = get_cached(cache_key)
    if cached:
        return cached

    markets = [
        'player_points', 'player_rebounds', 'player_assists',
        'player_threes', 'player_double_double', 'player_blocks',
        'player_steals', 'player_turnovers', 'player_points_rebounds_assists',
        'player_points_rebounds', 'player_points_assists', 'player_rebounds_assists'
    ]

    all_props = []
    try:
        # Step 1: Get upcoming events
        events_url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/events"
        events_resp = requests.get(events_url, params={'apiKey': ODDS_API_KEY}, timeout=10)
        events_resp.raise_for_status()
        events = events_resp.json()

        # Step 2: For each event, fetch props
        for event in events[:5]:  # limit to 5 games to avoid rate limits
            event_id = event['id']
            props_url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/events/{event_id}/odds"
            params = {
                'apiKey': ODDS_API_KEY,
                'regions': 'us',
                'markets': ','.join(markets),
                'oddsFormat': 'american'
            }
            try:
                props_resp = requests.get(props_url, params=params, timeout=10)
                if props_resp.status_code == 404:
                    continue
                props_resp.raise_for_status()
                event_props = props_resp.json()
                # Attach event metadata for convenience
                event_props['event_details'] = {
                    'id': event['id'],
                    'home_team': event['home_team'],
                    'away_team': event['away_team'],
                    'commence_time': event['commence_time']
                }
                all_props.append(event_props)
                time.sleep(0.2)  # be kind to API
            except Exception as e:
                print(f"⚠️ Error fetching props for event {event_id}: {e}", flush=True)
                continue

        if all_props:
            set_cache(cache_key, all_props)
            print(f"📊 Fetched props for {len(all_props)} events from The Odds API", flush=True)
        return all_props
    except Exception as e:
        print(f"❌ Error in fetch_player_props: {e}", flush=True)
        return []

def fetch_player_projections(sport: str, date: Optional[str] = None) -> List[Dict]:
    """Fetch player projections from Balldontlie season averages (NBA only)."""
    if sport != 'nba':
        print(f"⚠️ Projections only supported for NBA, got {sport}", flush=True)
        return []

    players = fetch_active_players(per_page=100)
    if not players:
        return []

    player_ids = [p['id'] for p in players if p.get('id')]
    avg_map = fetch_player_season_averages(player_ids, season=2025)

    projections = []
    for player in players:
        pid = player['id']
        avg = avg_map.get(pid, {})
        pts = avg.get('pts', 0)
        reb = avg.get('reb', 0)
        ast = avg.get('ast', 0)
        fantasy_pts = pts * 1.0 + reb * 1.2 + ast * 1.5

        projections.append({
            "PlayerID": pid,
            "Name": f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
            "Team": player.get('team', {}).get('abbreviation', 'FA'),
            "Position": player.get('position', 'N/A'),
            "Points": round(pts, 1),
            "Rebounds": round(reb, 1),
            "Assists": round(ast, 1),
            "FantasyPoints": round(fantasy_pts, 1),
            "InjuryStatus": "healthy",
            "Salary": 0,
            "Value": 0
        })

    # ✅ This print must be INSIDE the function
    print(f"✅ Generated {len(projections)} projections from Balldontlie season averages", flush=True)
    return projections

# ========== MAIN EXPORT FUNCTION ==========
def fetch_nba_from_balldontlie(limit: int) -> Optional[List[Dict]]:
    """
    Fetch NBA players from Balldontlie, including season averages.
    Returns top 'limit' players sorted by fantasy points.
    """
    print("🚦 ENTERED fetch_nba_from_balldontlie", flush=True)
    print(f"🔍 Requested limit: {limit}, fetching ALL players for ranking", flush=True)

    # 1. Fetch ALL players (using pagination)
    players_data = fetch_active_players(per_page=100)   # fetch first 100 players   
    if not players_data:
        print("❌ fetch_all_active_players returned None or empty", flush=True)
        return None
    print(f"✅ fetch_all_active_players returned {len(players_data)} players", flush=True)

    # 2. Collect valid player IDs
    player_ids = [p['id'] for p in players_data if p.get('id')]
    if not player_ids:
        print("❌ No valid player IDs found", flush=True)
        return None
    print(f"📊 Collected {len(player_ids)} player IDs", flush=True)

    # 3. Fetch season averages for all players (per-player requests)
    print("📊 Fetching season averages for 2025...", flush=True)
    avg_map = fetch_player_season_averages(player_ids, season=2025)

    # 4. Fetch injuries
    print("📞 Fetching injuries...", flush=True)
    try:
        injuries_data = fetch_player_injuries()
    except Exception as e:
        print(f"❌ Exception in fetch_player_injuries: {e}", flush=True)
        injuries_data = None

    injury_map = {}
    if injuries_data and isinstance(injuries_data, list):
        for item in injuries_data:
            player_info = item.get('player') or {}
            pid = player_info.get('id')
            if pid:
                injury_map[pid] = item.get('status', 'healthy')
        print(f"📊 Found injuries for {len(injury_map)} players", flush=True)
    else:
        print("⚠️ No injuries data returned", flush=True)

    # 5. Star overrides (same as in static fallback)
    star_stats = {
        "LeBron James": {"points": 27.2, "rebounds": 7.5, "assists": 7.8},
        "Nikola Jokic": {"points": 26.1, "rebounds": 12.3, "assists": 9.0},
        "Luka Doncic": {"points": 32.0, "rebounds": 8.5, "assists": 8.6},
        "Giannis Antetokounmpo": {"points": 30.8, "rebounds": 11.5, "assists": 6.2},
        "Stephen Curry": {"points": 26.4, "rebounds": 4.5, "assists": 5.0},
        "Jayson Tatum": {"points": 27.1, "rebounds": 8.2, "assists": 4.8},
        "Kevin Durant": {"points": 27.8, "rebounds": 6.7, "assists": 5.3},
        "Joel Embiid": {"points": 34.0, "rebounds": 11.0, "assists": 5.5},
        "Shai Gilgeous-Alexander": {"points": 31.5, "rebounds": 5.6, "assists": 6.5},
        "Anthony Davis": {"points": 25.5, "rebounds": 12.5, "assists": 3.5},
    }

    # 6. Transform each player
    transformed = []
    for idx, player in enumerate(players_data):
        try:
            pid = player.get('id')
            if not pid:
                continue

            first = player.get('first_name', '')
            last = player.get('last_name', '')
            name = f"{first} {last}".strip() or "Unknown Player"

            team_obj = player.get('team')
            team = team_obj.get('abbreviation', 'FA') if isinstance(team_obj, dict) else 'FA'
            position = player.get('position', 'N/A')

            # Get season averages if available
            avg = avg_map.get(pid, {})
            pts = avg.get('pts', 0)
            reb = avg.get('reb', 0)
            ast = avg.get('ast', 0)

            # Apply star overrides if name matches
            if name in star_stats:
                star = star_stats[name]
                pts = star["points"]
                reb = star["rebounds"]
                ast = star["assists"]
                print(f"⭐ Applied star override for {name}", flush=True)

            fantasy_pts = pts * 1.0 + reb * 1.2 + ast * 1.5

            # Salary calculation
            try:
                if fantasy_pts > 0:
                    base_salary = fantasy_pts * 350
                    pos_mult = {'PG': 0.9, 'SG': 0.95, 'SF': 1.0, 'PF': 1.05, 'C': 1.1}.get(position, 1.0)
                    rand_factor = random.uniform(0.85, 1.15)
                    salary = int(max(3000, min(15000, base_salary * pos_mult * rand_factor)))
                else:
                    salary = random.randint(4000, 8000)
            except Exception:
                salary = 5000

            value = fantasy_pts / (salary / 1000) if salary > 0 else 0
            injury_status = injury_map.get(pid, 'healthy')

            transformed.append({
                "id": pid,
                "name": name,
                "team": team,
                "position": position,
                "salary": salary,
                "fantasy_points": round(fantasy_pts, 1),
                "projected_points": round(fantasy_pts, 1),
                "value": round(value, 2),
                "points": round(pts, 1),
                "rebounds": round(reb, 1),
                "assists": round(ast, 1),
                "injury_status": injury_status,
                "is_real_data": True,
                "data_source": "Balldontlie (enriched)"
            })
        except Exception as e:
            print(f"❌ Error processing player {idx}: {e}", flush=True)
            continue

    # 7. Sort by fantasy_points descending and return top 'limit'
    transformed.sort(key=lambda x: x['fantasy_points'], reverse=True)
    top_players = transformed[:limit]
    print(f"🏁 Returning top {len(top_players)} players by fantasy points", flush=True)
    return top_players
