#!/usr/bin/env python3
import requests
import json

BASE_URL = "https://python-api-fresh-production.up.railway.app"

def test_nba_data():
    """Test the updated NBA data."""
    
    # Get player list
    print("📊 Fetching NBA players...")
    response = requests.get(f"{BASE_URL}/api/fantasy/players", 
                           params={"sport": "nba", "limit": 5})
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Found {data.get('total', 0)} players")
        print("\n🏀 Top 5 Players:")
        for i, player in enumerate(data.get('players', [])[:5], 1):
            print(f"  {i}. {player.get('name')} - {player.get('team')}")
            print(f"     PPG: {player.get('points_per_game', 0):.1f}, "
                  f"RPG: {player.get('rebounds_per_game', 0):.1f}, "
                  f"APG: {player.get('assists_per_game', 0):.1f}")
            print(f"     Fantasy: {player.get('fantasy_points', 0):.1f}")
    else:
        print(f"❌ Error: {response.status_code}")

if __name__ == "__main__":
    test_nba_data()
