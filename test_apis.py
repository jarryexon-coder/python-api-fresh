import requests
from datetime import datetime

# API Keys Configuration - Only the working/essential ones
API_KEYS = {
    "SPORTSDATA_API_KEY": "d852ba32125e4977bf3bf154f1b0f349",  # ✅ Works for NBA/NFL/NHL/MLB
    "THE_ODDS_API_KEY": "052f3b960d3b195ccba0d12928de220e",  # ✅ Working
    "DEEPSEEK_API_KEY": "sk-217ae37717904411b4bf6c06353312fd",  # ✅ Working
    "NEWS_API_KEY": "0bcba4646f0a4963a1b72c3e3f1ebaa1",  # ✅ Working
    "RAPIDAPI_PLAYER_PROPS": "a0e5e0f406mshe0e4ba9f4f4daeap19859djsnfd92d0da5884",  # ✅ Working
    "RAPIDAPI_PREDICTIONS": "cdd1cfc95bmsh3dea79dcd1be496p167ea1jsnb355ed1075ec",  # ✅ Now with correct host
}


# Minimal test functions for your working APIs
def test_sportsdata():
    """Test SportsData.io - Your core data source"""
    try:
        response = requests.get(
            f"https://api.sportsdata.io/v3/nba/scores/json/GamesByDate/{datetime.now().strftime('%Y-%m-%d')}",
            params={"key": API_KEYS["SPORTSDATA_API_KEY"]},
            timeout=10,
        )
        if response.status_code == 200:
            games = response.json()
            return f"✅ SportsData.io: {len(games)} NBA games today"
        return f"❌ SportsData.io: {response.status_code}"
    except Exception as e:
        return f"❌ SportsData.io: {str(e)[:50]}"


def test_oddsapi():
    """Test The Odds API - Your betting data"""
    try:
        response = requests.get(
            "https://api.the-odds-api.com/v4/sports/basketball_nba/odds",
            params={
                "apiKey": API_KEYS["THE_ODDS_API_KEY"],
                "regions": "us",
                "markets": "h2h",
                "oddsFormat": "american",
            },
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json()
            return f"✅ The Odds API: {len(data)} games with odds"
        return f"❌ The Odds API: {response.status_code}"
    except Exception as e:
        return f"❌ The Odds API: {str(e)[:50]}"


def test_deepseek():
    """Test DeepSeek API - Your AI predictions"""
    try:
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {API_KEYS['DEEPSEEK_API_KEY']}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": "Test"}],
                "max_tokens": 5,
            },
            timeout=10,
        )
        if response.status_code == 200:
            return "✅ DeepSeek API: Working"
        return f"❌ DeepSeek API: {response.status_code}"
    except Exception as e:
        return f"❌ DeepSeek API: {str(e)[:50]}"


def test_newsapi():
    """Test News API - Your news/sentiment data"""
    try:
        response = requests.get(
            "https://newsapi.org/v2/top-headlines",
            params={"apiKey": API_KEYS["NEWS_API_KEY"], "country": "us", "pageSize": 1},
            timeout=10,
        )
        if response.status_code == 200:
            return "✅ News API: Working"
        return f"❌ News API: {response.status_code}"
    except Exception as e:
        return f"❌ News API: {str(e)[:50]}"


def test_rapidapi_injuries():
    """Test RapidAPI Injury Data"""
    try:
        response = requests.get(
            "https://nba-injury-data.p.rapidapi.com/injuries/nba/2024-11-22",
            headers={
                "X-RapidAPI-Key": API_KEYS["RAPIDAPI_PLAYER_PROPS"],
                "X-RapidAPI-Host": "nba-injury-data.p.rapidapi.com",
            },
            timeout=10,
        )
        if response.status_code == 200:
            return "✅ RapidAPI Injuries: Working"
        return f"❌ RapidAPI Injuries: {response.status_code}"
    except Exception as e:
        return f"❌ RapidAPI Injuries: {str(e)[:50]}"


def test_rapidapi_predictions():
    """Test RapidAPI Predictions with correct hostname"""
    try:
        response = requests.get(
            "https://basketball-predictions1.p.rapidapi.com/api/v2/predictions",
            headers={
                "X-RapidAPI-Key": API_KEYS["RAPIDAPI_PREDICTIONS"],
                "X-RapidAPI-Host": "basketball-predictions1.p.rapidapi.com",
            },
            params={"league": "nba"},
            timeout=10,
        )
        if response.status_code == 200:
            return "✅ RapidAPI Predictions: Working"
        return f"❌ RapidAPI Predictions: {response.status_code}"
    except Exception as e:
        return f"❌ RapidAPI Predictions: {str(e)[:50]}"


def test_all_sportsdata_services():
    """Quick test to confirm SportsData.io works for all sports"""
    sports = [("NBA", "nba"), ("NFL", "nfl"), ("NHL", "nhl"), ("MLB", "mlb")]

    results = []
    for sport_name, sport_code in sports:
        try:
            response = requests.get(
                f"https://api.sportsdata.io/v3/{sport_code}/scores/json/AreAnyGamesInProgress",
                params={"key": API_KEYS["SPORTSDATA_API_KEY"]},
                timeout=5,
            )
            if response.status_code == 200:
                results.append(f"✅ {sport_name}")
            else:
                results.append(f"⚠️ {sport_name}: {response.status_code}")
        except:
            results.append(f"❌ {sport_name}")

    return " | ".join(results)


if __name__ == "__main__":
    print("=" * 60)
    print("🎯 LEAN API TEST - WORKING ENDPOINTS ONLY")
    print("=" * 60)

    # Run all tests
    tests = [
        ("SportsData.io (NBA)", test_sportsdata),
        ("SportsData.io (All Sports)", test_all_sportsdata_services),
        ("The Odds API", test_oddsapi),
        ("DeepSeek API", test_deepseek),
        ("News API", test_newsapi),
        ("RapidAPI Injuries", test_rapidapi_injuries),
        ("RapidAPI Predictions", test_rapidapi_predictions),
    ]

    results = []
    for name, test_func in tests:
        result = test_func()
        print(f"{name}: {result}")
        results.append(result)

    print("\n" + "=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)

    working = sum(1 for r in results if r.startswith("✅"))
    total = len(results)

    print(f"Working APIs: {working}/{total}")
    print(f"Success Rate: {working/total*100:.0f}%")

    if working >= 5:
        print("\n🎉 READY TO BUILD!")
        print("You have all essential APIs working:")
        print("1. SportsData.io - Game data")
        print("2. The Odds API - Betting markets")
        print("3. DeepSeek - AI predictions")
        print("4. News API - News/sentiment")
        print("5. RapidAPI - Injuries & Predictions")

        print("\n" + "=" * 60)
        print("🚀 NEXT STEP: CREATE YOUR .ENV FILE")
        print("=" * 60)
        print("Create a `.env` file with these keys:")
        print(f"SPORTSDATA_KEY={API_KEYS['SPORTSDATA_API_KEY']}")
        print(f"ODDS_API_KEY={API_KEYS['THE_ODDS_API_KEY']}")
        print(f"DEEPSEEK_KEY={API_KEYS['DEEPSEEK_API_KEY']}")
        print(f"NEWS_API_KEY={API_KEYS['NEWS_API_KEY']}")
        print(f"RAPIDAPI_INJURY_KEY={API_KEYS['RAPIDAPI_PLAYER_PROPS']}")
        print(f"RAPIDAPI_PREDICTIONS_KEY={API_KEYS['RAPIDAPI_PREDICTIONS']}")
        print(f"RAPIDAPI_PREDICTIONS_HOST=basketball-predictions1.p.rapidapi.com")

        print("\n" + "=" * 60)
        print("💡 QUICK START TEMPLATE")
        print("=" * 60)
        print("""# main.py
import os
import requests
from datetime import datetime

class SportsAnalytics:
    def __init__(self):
        self.sportsdata_key = os.getenv('SPORTSDATA_KEY')
        self.odds_key = os.getenv('ODDS_API_KEY')
        self.deepseek_key = os.getenv('DEEPSEEK_KEY')
    
    def get_todays_games(self):
        url = f"https://api.sportsdata.io/v3/nba/scores/json/GamesByDate/{datetime.now().strftime('%Y-%m-%d')}"
        response = requests.get(url, params={'key': self.sportsdata_key})
        return response.json()
    
    def get_odds(self):
        url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
        params = {
            'apiKey': self.odds_key,
            'regions': 'us',
            'markets': 'h2h,spreads,totals'
        }
        response = requests.get(url, params=params)
        return response.json()
    
    def get_ai_prediction(self, game_data):
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.deepseek_key}",
            "Content-Type": "application/json"
        }
        prompt = f"Analyze this NBA game and provide prediction: {game_data}"
        payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}]
        }
        response = requests.post(url, headers=headers, json=payload)
        return response.json()

# Start building!
app = SportsAnalytics()
print("🎯 Ready to build your sports analytics app!")""")
