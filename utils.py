import os
import time
import json
import hashlib
import random
import asyncio
import requests
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Optional, Dict, Any, List, Tuple
import jwt
from flask import request, jsonify
import firebase_admin
from firebase_admin import auth

def generate_token(user_id):
    """Generate a JWT token for internal use (if needed)."""
    secret = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
    return jwt.encode(
        {'user_id': user_id},
        secret,
        algorithm='HS256'
    )

def verify_token(token):
    """Verify a JWT token (internal)."""
    try:
        secret = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
        payload = jwt.decode(token, secret, algorithms=['HS256'])
        return payload.get('user_id')
    except jwt.InvalidTokenError:
        return None

def verify_firebase_token(token):
    """Verify a Firebase ID token (client‑side token)."""
    try:
        # token may come with "Bearer " prefix
        if token.startswith('Bearer '):
            token = token.split(' ')[1]
        decoded = auth.verify_id_token(token)
        return decoded.get('uid')
    except Exception as e:
        print(f"Firebase token verification failed: {e}")
        return None

def login_required(f):
    """Decorator that checks for a valid Firebase token in the Authorization header."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({'error': 'Missing Authorization header'}), 401
        # Extract token
        token = auth_header.replace('Bearer ', '')
        user_id = verify_firebase_token(token)
        if not user_id:
            return jsonify({'error': 'Invalid or expired token'}), 401
        # Store user_id in request context for downstream use
        request.user_id = user_id
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorator that checks for admin privileges (requires user to exist in Firestore with role='admin')."""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        # Get user from Firestore
        user_id = request.user_id
        # Replace 'users' with your actual collection name
        doc = firestore.client().collection('users').document(user_id).get()
        if not doc.exists:
            return jsonify({'error': 'User not found'}), 403
        user_data = doc.to_dict()
        if user_data.get('role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

# -------------------- API Configurations --------------------
API_CONFIG = {
    "sportsdata_nba": {
        "key": os.environ.get("SPORTSDATA_NBA_KEY", ""),
        "base_url": "https://api.sportsdata.io/v3/nba",
        "working": bool(os.environ.get("SPORTSDATA_NBA_KEY")),
        "name": "SportsData.io NBA",
    },
    # Add other sports as needed
}


# -------------------- Odds & Value Calculations --------------------
def american_to_implied(odds):
    """Convert American odds to implied probability."""
    if odds is None:
        return 0.5
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return -odds / (-odds + 100)


def decimal_to_american(decimal_odds):
    """Convert decimal odds to American format."""
    if decimal_odds >= 2.0:
        return int((decimal_odds - 1) * 100)
    else:
        return int(-100 / (decimal_odds - 1))


def calculate_confidence(over_odds, under_odds):
    """Calculate a confidence score from over/under odds."""
    if not over_odds or not under_odds:
        return 60

    def to_decimal(american):
        if american > 0:
            return (american / 100) + 1
        else:
            return (100 / abs(american)) + 1

    over_dec = to_decimal(over_odds)
    under_dec = to_decimal(under_odds)
    avg_odds = (over_dec + under_dec) / 2
    if avg_odds < 1.8:
        return 85
    elif avg_odds > 2.2:
        return 70
    else:
        return 75


def is_cache_fresh(sport: str, ttl_seconds: int = 300) -> bool:
    """
    Check if cached player props for the given sport are still fresh.
    Uses the existing `_is_cache_valid` helper with a constructed cache key.
    """
    cache_key = f"player_props_{sport}"
    return _is_cache_valid(cache_key, ttl_seconds)


def get_confidence_level(score):
    """Convert numeric score to confidence level string."""
    if score >= 80:
        return "very-high"
    elif score >= 70:
        return "high"
    elif score >= 60:
        return "medium"
    elif score >= 50:
        return "low"
    else:
        return "very-low"


# -------------------- Team Name Helpers --------------------
def get_full_team_name(team_abbrev):
    """Map NBA team abbreviation to full name (fallback to abbrev)."""
    nba_teams = {
        "LAL": "Los Angeles Lakers",
        "GSW": "Golden State Warriors",
        "BOS": "Boston Celtics",
        "PHX": "Phoenix Suns",
        "MIL": "Milwaukee Bucks",
        "DEN": "Denver Nuggets",
        "DAL": "Dallas Mavericks",
        "MIA": "Miami Heat",
        "PHI": "Philadelphia 76ers",
        "LAC": "Los Angeles Clippers",
    }
    return nba_teams.get(team_abbrev, team_abbrev)


# -------------------- Data Sanitization --------------------
def sanitize_data(obj):
    """Recursively convert sets to lists and handle unexpected types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: sanitize_data(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_data(v) for v in obj]
    elif isinstance(obj, set):
        print(f"⚠️ Converting set to list: {obj}")
        return list(obj)
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        print(f"⚠️ Unexpected type {type(obj)} – converting to string")
        return str(obj)


# -------------------- Token Counting --------------------
def num_tokens_from_string(string: str, model: str = "gpt-3.5-turbo") -> int:
    """Return token count for a string. Falls back to word count * 1.3 if tiktoken fails."""
    try:
        import tiktoken

        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(string))
    except Exception:
        return int(len(string.split()) * 1.3)


# -------------------- Async Helper --------------------
def run_async(coro):
    """Run an async coroutine synchronously (for compatibility)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# -------------------- File Loading --------------------
def safe_load_json(filename, default=None):
    """Safely load a JSON file; return default if file not found or invalid."""
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"⚠️ Could not load {filename}: {e}")
        return default if default is not None else []


# -------------------- HTTP Request with Retry --------------------
def make_api_request_with_retry(
    url, headers=None, params=None, method="GET", max_retries=3
):
    """
    Make an HTTP request with exponential backoff retry.
    Supports GET and POST; returns response object or None after final failure.
    """
    for attempt in range(max_retries):
        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=30)
            elif method.upper() == "POST":
                response = requests.post(url, headers=headers, json=params, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")

            if response.status_code == 200:
                return response
            elif response.status_code == 429:  # Rate limited
                wait_time = (2**attempt) + random.random()
                print(
                    f"⚠️ Rate limited, waiting {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(wait_time)
                continue
            elif response.status_code >= 500:  # Server error
                wait_time = (1.5**attempt) + random.random()
                print(
                    f"⚠️ Server error {response.status_code}, waiting {wait_time:.1f}s"
                )
                time.sleep(wait_time)
                continue
            else:
                # Non-retryable status (e.g., 400, 404)
                return response
        except requests.exceptions.Timeout:
            wait_time = (2**attempt) + random.random()
            print(
                f"⚠️ Timeout, waiting {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})"
            )
            time.sleep(wait_time)
            continue
        except Exception as e:
            print(f"⚠️ Request error: {e}")
            if attempt == max_retries - 1:
                raise
            time.sleep(1)
    return None


# -------------------- balldontlie API Helper --------------------
def balldontlie_request(
    endpoint: str, params: Optional[dict] = None
) -> Tuple[Optional[dict], Optional[str]]:
    """
    Make an authenticated request to the balldontlie API.
    Returns (data_dict, error_message). On success, error_message is None.
    Requires environment variables:
        BALLDONTLIE_API_KEY - your API key
        BALLDONTLIE_BASE_URL - base URL (default: https://api.balldontlie.io/v1)
    """
    api_key = os.environ.get("BALLDONTLIE_API_KEY")
    base_url = os.environ.get(
        "BALLDONTLIE_BASE_URL", "https://api.balldontlie.io/atp/v1"
    )

    if not api_key:
        return None, "BallDonLie API key not configured"

    url = f"{base_url}/{endpoint.lstrip('/')}"
    headers = {"Authorization": api_key}

    response = make_api_request_with_retry(
        url, headers=headers, params=params, method="GET"
    )
    if response is None:
        return None, "Request failed after retries"
    if response.status_code != 200:
        return None, f"HTTP {response.status_code}: {response.text}"
    try:
        return response.json(), None
    except Exception as e:
        return None, f"JSON decode error: {e}"


# -------------------- Cache Helpers --------------------
def get_cache_key(endpoint, params):
    """Generate a consistent cache key from endpoint and parameters."""
    key_str = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
    return hashlib.md5(key_str.encode()).hexdigest()


def is_cache_valid(cache_entry, cache_minutes=5):
    """Check if a cache entry is still valid."""
    if not cache_entry:
        return False
    cache_age = time.time() - cache_entry["timestamp"]
    return cache_age < (cache_minutes * 60)


def should_skip_cache(args):
    """Check if force refresh is requested."""
    return args.get("force", "").lower() in ("true", "1", "yes")


# -------------------- In‑Memory Caching Decorator --------------------
def cached(ttl_seconds=300):
    """
    Decorator to cache the result of a function in memory.
    The cache key is derived from the function name and arguments.
    """
    cache = {}

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Build a cache key from function name + args + kwargs
            key_parts = [func.__name__]
            key_parts.extend(str(arg) for arg in args)
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            key = hashlib.md5(":".join(key_parts).encode()).hexdigest()

            now = time.time()
            if key in cache and (now - cache[key]["timestamp"]) < ttl_seconds:
                print(f"✅ Cache hit for {func.__name__}")
                return cache[key]["value"]

            result = func(*args, **kwargs)
            cache[key] = {"value": result, "timestamp": now}
            return result

        return wrapper

    return decorator


# -------------------- Redis Caching Decorator (requires a Redis client) --------------------
def cached_redis(redis_client):
    """
    Factory that returns a decorator for Redis caching.
    Usage:
        redis_client = redis.Redis(...)
        @cached_redis(redis_client)(ttl_seconds=300)
        def my_function(...): ...
    """

    def decorator(ttl_seconds=300):
        def inner_decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                key = get_cache_key(func.__name__, {"args": args, "kwargs": kwargs})
                cached = redis_client.get(key)
                if cached:
                    print(f"✅ Redis cache hit for {func.__name__}")
                    return json.loads(cached)
                result = func(*args, **kwargs)
                redis_client.setex(key, ttl_seconds, json.dumps(result))
                return result

            return wrapper

        return inner_decorator

    return decorator


# -------------------- Rate Limiting Helper --------------------
def is_rate_limited(ip, endpoint, limit=60, window=60, request_log=None):
    """
    Simple in‑memory rate limiter.
    Requires a request_log dict (defaultdict(list)) to be passed.
    """
    if request_log is None:
        return False
    current_time = time.time()
    window_start = current_time - window
    request_log[ip] = [t for t in request_log[ip] if t > window_start]
    if len(request_log[ip]) >= limit:
        return True
    request_log[ip].append(current_time)
    return False


# -------------------- NHL & MLB Caching Helpers (added for consistency) --------------------
# Global cache dictionaries – used by _get_cached and _set_cache
_cache = {}
_cache_timestamp = {}


def _is_cache_valid(key, ttl_seconds=3600):
    """Check if a cached entry (by key) is still fresh."""
    if key not in _cache_timestamp:
        return False
    return (datetime.now() - _cache_timestamp[key]).total_seconds() < ttl_seconds


def _get_cached(key):
    """Retrieve a value from the global cache if it's still valid."""
    return _cache.get(key) if _is_cache_valid(key) else None


def _set_cache(key, value):
    """Store a value in the global cache with current timestamp."""
    _cache[key] = value
    _cache_timestamp[key] = datetime.now()
