"""Centralized configuration for February 2026"""
import os
from datetime import datetime

class Config:
    # 2026 Season Status
    CURRENT_DATE = "2026-02-11"
    NBA_SEASON = "2025-26"
    NHL_SEASON = "2025-26"
    NFL_SEASON = "2026"
    MLB_SEASON = "2026"
    
    # Key Dates 2026
    NBA_ALL_STAR = "2026-02-15"
    NBA_TRADE_DEADLINE = "2026-02-19"
    NHL_TRADE_DEADLINE = "2026-03-07"
    MLB_SPRING_TRAINING = "2026-02-22"
    
    # API Endpoints 2026
    THE_ODDS_API = "https://api.the-odds-api.com/v4"
    SPORTSDATA_NBA = "https://api.sportsdata.io/v3/nba"
    SPORTSDATA_NHL = "https://api.sportsdata.io/v3/nhl"
    
    # Cache Settings
    CACHE_TTL = 300  # 5 minutes
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
    
    # Parlay Limits
    MAX_PARLAY_LEGS = 20
    MAX_TEASER_POINTS = 7
    MAX_ROUND_ROBIN_COMBOS = 10
