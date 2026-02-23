import os
import time
import requests
from typing import Optional, Dict

# API configurations (remove sportsdata entries if not used)
API_CONFIG = {
    'sportsdata_nba': {
        'key': os.environ.get('SPORTSDATA_NBA_KEY', ''),
        'base_url': 'https://api.sportsdata.io/v3/nba',
        'working': bool(os.environ.get('SPORTSDATA_NBA_KEY')),
        'name': 'SportsData.io NBA'
    },
    # ... other sports if needed
}

def make_api_request_with_retry(url: str, headers: Optional[Dict] = None, params: Optional[Dict] = None,
                                max_retries: int = 3, backoff_factor: float = 0.5) -> Optional[requests.Response]:
    """Make an API request with exponential backoff retry."""
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            if resp.status_code == 200:
                return resp
            elif resp.status_code >= 500 and attempt < max_retries - 1:
                time.sleep(backoff_factor * (2 ** attempt))
                continue
            else:
                print(f"⚠️ API request failed with status {resp.status_code}: {url}")
                return None
        except Exception as e:
            print(f"❌ API request error (attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(backoff_factor * (2 ** attempt))
            else:
                return None
    return None
