import requests
import json

BASE_URL = "https://python-api-fresh-production.up.railway.app"
print(f"🎯 Final test of all endpoints at: {BASE_URL}")

# Test all endpoints your React app uses
endpoints = [
    ("Health", "/api/health", {}),
    ("Players", "/api/players", {"sport": "nba", "limit": "5"}),
    ("Fantasy Teams", "/api/fantasy/teams", {"sport": "nba"}),
    ("PrizePicks", "/api/prizepicks/selections", {"sport": "nba"}),
    ("Sports Wire", "/api/sports-wire", {"sport": "nba"}),
    ("Analytics", "/api/analytics", {"sport": "nba"}),
    ("Predictions", "/api/predictions", {"sport": "nba"}),
    ("Parlay Suggestions", "/api/parlay/suggestions", {"sport": "all", "limit": "4"}),
    ("Odds Games", "/api/odds/games", {"region": "today"}),
    ("Player Trends", "/api/players/trends", {"sport": "nba"}),
    ("Prediction Outcomes", "/api/predictions/outcomes", {"sport": "nba"}),
    ("Secret Phrases", "/api/secret/phrases", {})
]

all_working = True
for name, endpoint, params in endpoints:
    try:
        response = requests.get(BASE_URL + endpoint, params=params, timeout=30)
        
        if response.status_code == 200:
            try:
                data = response.json()
                success = data.get('success', False)
                count = data.get('count', 0)
                
                if success:
                    print(f"✅ {name}: Status {response.status_code}, Count: {count}")
                else:
                    print(f"❌ {name}: Status {response.status_code}, Error: {data.get('error', 'Unknown')}")
                    all_working = False
            except json.JSONDecodeError:
                print(f"❌ {name}: Invalid JSON response")
                all_working = False
        else:
            print(f"❌ {name}: Status {response.status_code}")
            all_working = False
            
    except Exception as e:
        print(f"❌ {name}: Connection error - {e}")
        all_working = False

print(f"\n{'='*60}")
if all_working:
    print("🎉 ALL ENDPOINTS WORKING! Your API is READY!")
    print("\n🚀 Update your React app to use:")
    print(f"   API URL: {BASE_URL}")
    print("\n📋 Your React app pages will now show:")
    print("   • FantasyHub: Players & Teams ✅")
    print("   • PlayerStats: Sports News ✅")
    print("   • DailyPicks: (Fix React FormControl error)") 
    print("   • ParlayArchitect: Parlay Suggestions ✅")
    print("   • AdvancedAnalytics: Analytics Data ✅")
    print("   • PredictionsOutcome: Outcomes Data ✅")
    print("   • SecretPhrases: Phrases Data ✅")
    print("   • KalshiPage: Predictions Data ✅")
else:
    print("⚠️ Some endpoints still need fixing")
