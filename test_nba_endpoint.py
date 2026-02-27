# test_nba_endpoint.py
#!/usr/bin/env python3
"""
Test the NBA endpoint with static data.
"""

import requests
import json
import sys

def test_endpoint(base_url: str = "http://localhost:5000"):
    """Test the NBA endpoint with realtime=false."""
    url = f"{base_url}/api/player-stats?sport=nba&realtime=false"
    
    try:
        print(f"🔍 Testing: {url}")
        response = requests.get(url)
        
        if response.status_code != 200:
            print(f"❌ Error: HTTP {response.status_code}")
            return False
        
        data = response.json()
        
        # Check response structure
        print(f"✅ Response received")
        print(f"   is_real_data: {data.get('is_real_data')}")
        print(f"   data_source: {data.get('data_source')}")
        print(f"   players returned: {len(data.get('players', []))}")
        
        # Check first player
        if data.get('players'):
            p = data['players'][0]
            print(f"\n📊 Sample player: {p.get('name')} ({p.get('team')})")
            print(f"   Position: {p.get('position')}")
            print(f"   Games: {p.get('games')}")
            print(f"   PPG: {p.get('pts_per_game'):.1f}")
            print(f"   RPG: {p.get('reb_per_game'):.1f}")
            print(f"   APG: {p.get('ast_per_game'):.1f}")
            print(f"   Fantasy Points: {p.get('fantasy_points'):.1f}")
            print(f"   Injury Status: {p.get('injury_status')}")
        
        return True
        
    except requests.exceptions.ConnectionError:
        print(f"❌ Could not connect to {base_url}")
        print("   Make sure your Flask app is running")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    # Use command line argument for base URL if provided
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5000"
    success = test_endpoint(base_url)
    sys.exit(0 if success else 1)
