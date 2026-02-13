"""Background worker for generating parlay suggestions"""
import asyncio
import json
from datetime import datetime
from typing import List, Dict
import redis.asyncio as redis
from services.ai_parlay_service import AIParlayService
from services.nhl_parlay_service import NHLParlayService
from services.nba_parlay_service import NBAParlayService

class SuggestionWorker:
    """Background worker that pre-generates parlay suggestions"""
    
    def __init__(self):
        self.redis_client = redis.from_url('redis://localhost:6379')
        self.ai_service = AIParlayService()
        self.nhl_service = NHLParlayService()
        self.nba_service = NBAParlayService()
        self.cache_ttl = 300  # 5 minutes
        
    async def run(self):
        """Main worker loop"""
        while True:
            try:
                # Generate suggestions for each sport
                await self.generate_nba_suggestions()
                await self.generate_nhl_suggestions()
                await self.generate_cross_sport_suggestions()
                
                # Wait before next generation
                await asyncio.sleep(self.cache_ttl)
            except Exception as e:
                print(f"Worker error: {e}")
                await asyncio.sleep(60)
    
    async def generate_nba_suggestions(self):
        """Generate NBA parlay suggestions"""
        # Fetch NBA games
        games = await self.fetch_nba_games()
        
        # Generate suggestions
        suggestions = self.nba_service.generate_parlays(games, limit=10)
        
        # Cache in Redis
        await self.redis_client.setex(
            'parlay:suggestions:nba',
            self.cache_ttl,
            json.dumps(suggestions)
        )
        
        print(f"[{datetime.now()}] Generated {len(suggestions)} NBA suggestions")
    
    async def generate_nhl_suggestions(self):
        """Generate NHL parlay suggestions"""
        games = await self.fetch_nhl_games()
        suggestions = self.nhl_service.generate_parlays(games, limit=10)
        
        await self.redis_client.setex(
            'parlay:suggestions:nhl',
            self.cache_ttl,
            json.dumps(suggestions)
        )
        
        print(f"[{datetime.now()}] Generated {len(suggestions)} NHL suggestions")
    
    async def generate_cross_sport_suggestions(self):
        """Generate cross-sport parlay suggestions"""
        nba_games = await self.fetch_nba_games()
        nhl_games = await self.fetch_nhl_games()
        
        suggestions = self.ai_service.generate_cross_sport_parlays(
            nba_games[:2], 
            nhl_games[:2]
        )
        
        await self.redis_client.setex(
            'parlay:suggestions:cross',
            self.cache_ttl,
            json.dumps(suggestions)
        )

if __name__ == '__main__':
    worker = SuggestionWorker()
    asyncio.run(worker.run())
