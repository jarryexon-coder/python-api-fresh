import requests
from config.api_keys import APIConfig
from cache.odds_cache import OddsCache

class OddsAPIClient:
    def __init__(self):
        self.api_key = APIConfig.THE_ODDS_API_KEY
        self.base_url = APIConfig.THE_ODDS_API_BASE
        self.cache = OddsCache()
    
    def get_live_odds(self, sport, markets=None, regions='us'):
        """Fetch live odds from The Odds API"""
        cache_key = f"{sport}_{markets}_{regions}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
            
        # Real API call implementation
        # ... (code from enhanced endpoints)
