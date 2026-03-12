import requests
import json

BASE_URL = "https://python-api-fresh-production.up.railway.app"
print(f"Testing fixed endpoints at: {BASE_URL}")

endpoints = [
    ("/api/health", {}),
    ("/api/players", {"sport": "nba", "limit": "5"}),
    ("/api/fantasy/teams", {"sport": "nba"}),
    ("/api/prizepicks/selections", {"sport": "nba"}),
    ("/api/sports-wire", {"sport": "nba"}),
    ("/api/analytics", {"sport": "nba"}),
    ("/api/predictions", {"sport": "nba"}),
    ("/api/parlay/suggestions", {"sport": "all", "limit": "4"}),
    ("/api/odds/games", {"region": "today"}),
    ("/api/players/trends", {"sport": "nba"}),
    ("/api/predictions/outcomes", {"sport": "nba"}),
    ("/api/secret/phrases", {}),
]

for endpoint, params in endpoints:
    try:
        response = requests.get(BASE_URL + endpoint, params=params, timeout=30)
        data = response.json()

        print(f"\n🔍 {endpoint}:")
        print(f"   Status: {response.status_code}")
        print(f"   Success: {data.get('success', False)}")
        print(f"   Count: {data.get('count', 'N/A')}")
        print(f"   has_data: {data.get('has_data', 'N/A')}")
        print(f"   is_real_data: {data.get('is_real_data', 'N/A')}")

        if data.get("success") and data.get("count", 0) > 0:
            print(f"   ✅ WORKING WITH DATA")
        elif data.get("success"):
            print(f"   ⚠️  WORKING BUT NO DATA")
        else:
            print(f"   ❌ FAILED")

    except Exception as e:
        print(f"\n❌ {endpoint} ERROR: {e}")

print(f"\n{'='*60}")
print("🎯 Your React app pages should now show:")
print("   • PlayerStatsPage: News from /api/sports-wire")
print("   • DailyPicksPage: Fixed (was FormControl error)")
print("   • ParlayArchitect: Suggestions from /api/parlay/suggestions")
print("   • AdvancedAnalytics: Data from /api/analytics")
print("   • PredictionsOutcome: Data from /api/predictions/outcomes")
print("   • SecretPhrases: Data from /api/secret/phrases")
print("   • KalshiPage: Predictions from /api/predictions")
