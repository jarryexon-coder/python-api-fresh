"""Professional parlay calculation engine 2026"""
from typing import List, Dict
import math

class ParlayService2026:
    """Advanced parlay calculations with correlation bonuses"""
    
    @staticmethod
    def calculate_correlation(legs: List[Dict]) -> float:
        """Calculate correlation bonus for same game parlays"""
        correlation_score = 0.0
        # QB + WR correlation
        if any(l['market'] == 'Passing TDs' for l in legs) and \
           any(l['market'] == 'Receiving TDs' for l in legs):
            correlation_score += 0.15
        # Star player + team win
        if any(l.get('is_star', False) for l in legs) and \
           any(l['market'] == 'Moneyline' for l in legs):
            correlation_score += 0.10
        return min(correlation_score, 0.35)  # Max 35% bonus
    
    @staticmethod
    def calculate_teaser_odds(sport: str, points: float, legs: int) -> int:
        """2026 teaser odds tables"""
        odds_table = {
            'nfl': {6: -110, 6.5: -120, 7: -130},
            'nba': {6: -110, 6.5: -115, 7: -120}
        }
        base_odds = odds_table.get(sport, {}).get(points, -110)
        # Adjust for number of legs
        return base_odds - (legs - 2) * 10  # -120 for 3-leg, -130 for 4-leg
