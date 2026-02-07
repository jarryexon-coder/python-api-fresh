import requests
import json

BASE_URL = "https://python-api-fresh-production.up.railway.app"
print(f"Testing API at: {BASE_URL}")

endpoints = [
    ("/api/players", {"sport": "nba", "limit": "5"}),
    ("/api/fantasy/teams", {"sport": "nba"}),
    ("/api/prizepicks/selections", {"sport": "nba"})
]

for endpoint, params in endpoints:
    try:
        response = requests.get(BASE_URL + endpoint, params=params, timeout=30)
        data = response.json()
        
        print(f"\n🔍 {endpoint}:")
        print(f"   Status: {response.status_code}")
        print(f"   Success: {data.get('success', False)}")
        print(f"   Count: {data.get('count', 0)}")
        print(f"   Message: {data.get('message', 'N/A')}")
        
        if data.get('success'):
            print(f"   ✅ WORKING")
        else:
            print(f"   ❌ FAILED: {data.get('error', 'Unknown')}")
            
    except Exception as e:
        print(f"\n❌ {endpoint} ERROR: {e}")
