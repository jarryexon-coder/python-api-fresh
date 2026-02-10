import requests
import json

BASE_URL = "https://pleasing-determination-production.up.railway.app"

def test_endpoint(url, name):
    print(f"\n{'='*60}")
    print(f"🔍 Testing: {name}")
    print(f"URL: {url}")
    print(f"{'='*60}")
    
    try:
        response = requests.get(url, timeout=10)
        print(f"Status: {response.status_code}")
        print(f"Content-Type: {response.headers.get('Content-Type')}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                print(f"\n📊 Response keys: {list(data.keys())}")
                
                if 'message' in data:
                    print(f"Message: {data['message']}")
                
                if 'availableEndpoints' in data:
                    print(f"\nAvailable endpoints ({len(data['availableEndpoints'])}):")
                    for endpoint in data['availableEndpoints'][:15]:
                        print(f"  {endpoint}")
                    if len(data['availableEndpoints']) > 15:
                        print(f"  ... and {len(data['availableEndpoints']) - 15} more")
                
                # Check if this looks like our documentation response
                if 'api_sources' in data and 'documentation' in data:
                    print(f"\n⚠️  This appears to be a documentation/fallback response")
                    print(f"   Path in response: {data.get('path', 'N/A')}")
                
            except json.JSONDecodeError:
                print(f"\n❌ Response is not valid JSON")
                print(f"Preview: {response.text[:200]}")
        else:
            print(f"\n❌ Non-200 response: {response.text[:200]}")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")

# Test various endpoints
test_endpoint(f"{BASE_URL}/api/picks?sport=nba", "/api/picks")
test_endpoint(f"{BASE_URL}/api", "/api (root)")
test_endpoint(f"{BASE_URL}/api/", "/api/ (with slash)")
test_endpoint(f"{BASE_URL}/api/health", "/api/health")
test_endpoint(f"{BASE_URL}/api/prizepicks/selections?sport=nba", "/api/prizepicks/selections")

# Test if there's a catch-all
test_endpoint(f"{BASE_URL}/api/does-not-exist", "/api/does-not-exist")
test_endpoint(f"{BASE_URL}/api/picks/extra", "/api/picks/extra")

print(f"\n{'='*60}")
print("🎯 CONCLUSION")
print(f"{'='*60}")
print("If /api/picks returns documentation but /api/prizepicks/selections")
print("returns real data, then there's a route-specific issue with /api/picks")
