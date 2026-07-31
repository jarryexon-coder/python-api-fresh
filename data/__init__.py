"""
Data module for sports analytics API
Contains all static data structures
"""

from .nba_teams import NBA_TEAM_ABBR_TO_SHORT, NBA_TEAMS_FULL, NBA_TEAM_ABBR
from .beat_writers import NBA_BEAT_WRITERS, NFL_BEAT_WRITERS, BEAT_WRITERS_BY_SPORT
from .national_insiders import NATIONAL_INSIDERS
from .injury_data import INJURY_TYPES, get_fallback_nba_injuries, get_fallback_nfl_injuries
from .team_rosters import TEAM_ROSTERS
