import redis
import json
from datetime import timedelta

class OddsCache:
    def __init__(self):
        self.redis_client = redis.Redis(
            host='localhost',
            port=6379,
            decode_responses=True
        )
        self.default_ttl = timedelta(minutes=5)  # Odds change frequently
    
    def get(self, key):
        cached = self.redis_client.get(f"odds:{key}")
        return json.loads(cached) if cached else None
    
    def set(self, key, value, ttl=300):
        self.redis_client.setex(
            f"odds:{key}",
            ttl,
            json.dumps(value)
        )
