"""Correlation bonus calculation service - February 2026"""
from typing import List, Dict

class CorrelationService:
    """Calculates correlation bonuses for same game parlays"""
    
    CORRELATION_PATTERNS = {
        'qb_wr_td': {
            'markets': ['passing_touchdowns', 'receiving_touchdowns'],
            'bonus': 0.15,
            'description': 'QB-WR touchdown connection'
        },
        'star_player_win': {
            'markets': ['player_points', 'moneyline'],
            'bonus': 0.10,
            'description': 'Star player + team win'
        },
        'pitcher_strikeouts_team_total': {
            'markets': ['strikeouts', 'team_total'],
            'bonus': 0.12,
            'description': 'Pitcher strikeouts + team total'
        },
        'goalie_shutout_win': {
            'markets': ['shutout', 'moneyline'],
            'bonus': 0.18,
            'description': 'Goalie shutout + team win'
        },
        'points_rebounds_assists': {
            'markets': ['points', 'rebounds', 'assists'],
            'bonus': 0.08,
            'description': 'PRA correlated props'
        }
    }
    
    @classmethod
    def calculate_correlation_bonus(cls, legs: List[Dict]) -> float:
        """Calculate total correlation bonus for a set of legs"""
        total_bonus = 0.0
        markets = [leg.get('market', '').lower() for leg in legs]
        
        # Check each correlation pattern
        for pattern_key, pattern in cls.CORRELATION_PATTERNS.items():
            if all(market in markets for market in pattern['markets']):
                total_bonus += pattern['bonus']
        
        # Cap at 35% maximum bonus
        return min(total_bonus, 0.35)
    
    @classmethod
    def get_correlation_description(cls, legs: List[Dict]) -> List[str]:
        """Get descriptions of active correlations"""
        descriptions = []
        markets = [leg.get('market', '').lower() for leg in legs]
        
        for pattern_key, pattern in cls.CORRELATION_PATTERNS.items():
            if all(market in markets for market in pattern['markets']):
                descriptions.append(pattern['description'])
        
        return descriptions
