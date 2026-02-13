import os
from dotenv import load_dotenv

load_dotenv()

class APIConfig:
    # Your 15+ API keys loaded from environment
    DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')
    BALLDONTLIE_API_KEY = os.environ.get('BALLDONTLIE_API_KEY')
    KALSHI_ACCESS_KEY = os.environ.get('KALSHI_ACCESS_KEY')
    MLB_API_KEY = os.environ.get('MLB_API_KEY')
    NEWS_API_KEY = os.environ.get('NEWS_API_KEY')
    NFL_API_KEY = os.environ.get('NFL_API_KEY')
    NHL_API_KEY = os.environ.get('NHL_API_KEY')
    ODDS_API_KEY = os.environ.get('ODDS_API_KEY')
    RAPIDAPI_KEY_PLAYER_PROPS = os.environ.get('RAPIDAPI_KEY_PLAYER_PROPS')
    RAPIDAPI_KEY_PREDICTIONS = os.environ.get('RAPIDAPI_KEY_PREDICTIONS')
    SPORTS_RADAR_API_KEY = os.environ.get('SPORTS_RADAR_API_KEY')
    SPORTSDATA_API_KEY = os.environ.get('SPORTSDATA_API_KEY')
    SPORTSDATA_NBA_API_KEY = os.environ.get('SPORTSDATA_NBA_API_KEY')
    SPORTSDATA_NHL_API_KEY = os.environ.get('SPORTSDATA_NHL_API_KEY')
    THE_ODDS_API_KEY = os.environ.get('THE_ODDS_API_KEY')
    
    # API Endpoints
    THE_ODDS_API_BASE = "https://api.the-odds-api.com/v4"
    RAPIDAPI_HOST_PLAYER_PROPS = "player-prop-odds.p.rapidapi.com"
    RAPIDAPI_HOST_PREDICTIONS = "sport-prediction-api.p.rapidapi.com"
    DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"
    SPORTSDATA_API_BASE = "https://api.sportsdata.io/v3"
