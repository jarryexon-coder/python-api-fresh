# Save this as test_picks.py and run it
import requests
import json

def test_picks_endpoint():
    base_url = "https://pleasing-determination-production.up.railway.app"
    
    # Test 1: Check if endpoint exists
    print("🔍 Testing /api/picks endpoint...")
    try:
        response = requests.get(f"{base_url}/api/picks?sport=nba", timeout=10)
        print(f"Status Code: {response.status_code}")
        print(f"Content-Type: {response.headers.get('Content-Type')}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Keys in response: {list(data.keys())}")
            
            if 'picks' in data:
                print(f"✅ Found picks! Count: {data.get('count', 0)}")
                if data['picks']:
                    print(f"First pick: {data['picks'][0]}")
            else:
                print(f"❌ No 'picks' key found. Response: {json.dumps(data, indent=2)[:500]}")
        else:
            print(f"❌ Non-200 status: {response.text[:200]}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # Test 2: Check health endpoint
    print("\n🔍 Checking health endpoint...")
    try:
        response = requests.get(f"{base_url}/api/health", timeout=10)
        if response.status_code == 200:
            data = response.json()
            endpoints = data.get('endpoints', [])
            if '/api/picks' in endpoints:
                print("✅ /api/picks listed in health endpoint")
            else:
                print("❌ /api/picks NOT in health endpoint")
                print("Endpoints with 'pick':")
                for endpoint in endpoints:
                    if 'pick' in endpoint.lower():
                        print(f"  {endpoint}")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # Test 3: Try other similar endpoints
    print("\n🔍 Testing similar endpoints...")
    test_endpoints = [
        '/api/prizepicks/selections?sport=nba',
        '/api/players?sport=nba',
        '/api/analytics?sport=nba'
    ]
    
    for endpoint in test_endpoints:
        try:
            response = requests.get(f"{base_url}{endpoint}", timeout=5)
            print(f"{endpoint}: Status {response.status_code}")
        except Exception as e:
            print(f"{endpoint}: Error {e}")

if __name__ == "__main__":
    test_picks_endpoint()
