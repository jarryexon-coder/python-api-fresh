"""Data models for 2026 fantasy sports"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

@dataclass
class Player2026:
    id: str
    name: str
    team: str
    position: str
    sport: str
    salary: int
    fantasy_projection: float
    is_rookie: bool = False
    injury_status: str = "active"
    season: str = "2025-26"
    
@dataclass
class Parlay2026:
    id: str
    type: str  # standard, same_game, teaser, round_robin
    sport: str
    legs: List[dict]
    stake: float
    odds: int
    payout: float
    created_at: datetime
    correlation_bonus: float = 0.0
    
@dataclass
class PropBet2026:
    id: str
    player: str
    market: str
    line: float
    over_odds: int
    under_odds: int
    game_id: str
    game_time: datetime
    confidence: int
