import requests
import json

BASE_URL = "https://python-api-fresh-production.up.railway.app"

print("Your React app (FantasyHub) needs these endpoints:")
print("1. /api/players?sport=nba&limit=...")
print("2. /api/fantasy/teams?sport=nba")
print("3. /api/prizepicks/selections?sport=nba")
print()

# Test 1: Players endpoint (was 404)
print("🔍 Testing /api/players...")
try:
    resp = requests.get(f"{BASE_URL}/api/players", params={"sport": "nba", "limit": 5}, timeout=30)
    data = resp.json()
    print(f"   Status: {resp.status_code}")
    print(f"   Success: {data.get('success')}")
    print(f"   Players found: {data.get('count', 0)}")
    if data.get('players'):
        print(f"   First: {data['players'][0].get('name')}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 2: Fantasy teams endpoint (was empty)
print("\n🔍 Testing /api/fantasy/teams...")
try:
    resp = requests.get(f"{BASE_URL}/api/fantasy/teams", params={"sport": "nba"}, timeout=30)
    data = resp.json()
    print(f"   Status: {resp.status_code}")
    print(f"   Success: {data.get('success')}")
    print(f"   Teams found: {data.get('count', 0)}")
    print(f"   has_data: {data.get('has_data')}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 3: PrizePicks selections (already working)
print("\n🔍 Testing /api/prizepicks/selections...")
try:
    resp = requests.get(f"{BASE_URL}/api/prizepicks/selections", params={"sport": "nba"}, timeout=30)
    data = resp.json()
    print(f"   Status: {resp.status_code}")
    print(f"   Success: {data.get('success')}")
    print(f"   Selections: {data.get('count', 0)}")
    if data.get('selections'):
        s = data['selections'][0]
        print(f"   First: {s.get('player')} - {s.get('stat_type')} {s.get('line')}")
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n" + "="*60)
print("🎯 If all 3 endpoints work, update your React app to use:")
print(f"   API URL: {BASE_URL}")
print("\nIn your React app configuration:")
print("   REACT_APP_API_URL=https://python-api-fresh-production.up.railway.app")
