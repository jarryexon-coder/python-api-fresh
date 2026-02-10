import requests
import json

def test_fantasy_players_api():
    url = "https://pleasing-determination-production.up.railway.app/api/fantasy/players"
    params = {"sport": "nba"}
    
    print("🔍 Testing Fantasy Players API...")
    print(f"URL: {url}")
    print(f"Params: {params}")
    
    try:
        response = requests.get(url, params=params, timeout=10)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Success: {data.get('success')}")
            print(f"Count: {data.get('count')}")
            print(f"Players Count: {data.get('playersCount')}")
            print(f"Is Real Data: {data.get('is_real_data')}")
            
            players = data.get('players', [])
            print(f"\n📊 Total Players: {len(players)}")
            
            if players:
                print("\n👤 Player Details:")
                for i, player in enumerate(players[:5]):  # Show first 5 players
                    print(f"\nPlayer {i+1}:")
                    print(f"  Name: {player.get('name')}")
                    print(f"  Team: {player.get('team')}")
                    print(f"  Position: {player.get('position')}")
                    print(f"  Points: {player.get('points')}")
                    print(f"  Fantasy Points: {player.get('fantasy_points')}")
                    print(f"  Projected Points: {player.get('projected_points')}")
                    print(f"  Projection: {player.get('projection')}")
                    print(f"  Salary: {player.get('salary')}")
                    print(f"  Value: {player.get('value')}")
                    
                    # Check for projection data
                    has_projection = any([
                        player.get('projection'),
                        player.get('projected_points'),
                        player.get('projections')
                    ])
                    print(f"  Has Projection Data: {has_projection}")
            
            # Check data structure
            print("\n🔧 Data Structure Analysis:")
            if players:
                first_player = players[0]
                print(f"Keys in first player: {list(first_player.keys())}")
                
                # Check for critical fields
                critical_fields = ['name', 'team', 'position', 'points']
                missing_fields = [field for field in critical_fields if field not in first_player]
                if missing_fields:
                    print(f"⚠️ Missing critical fields: {missing_fields}")
                else:
                    print("✅ All critical fields present")
                    
                # Check projection fields
                projection_fields = ['projection', 'projected_points', 'fantasy_points', 'salary', 'value']
                available_projection_fields = [field for field in projection_fields if field in first_player and first_player[field]]
                print(f"📈 Available projection fields: {available_projection_fields}")
        
        else:
            print(f"❌ Error: {response.status_code}")
            print(f"Response: {response.text[:200]}")
            
    except Exception as e:
        print(f"❌ Exception: {e}")

def test_fantasy_teams_api():
    url = "https://pleasing-determination-production.up.railway.app/api/fantasy/teams"
    params = {"sport": "nba"}
    
    print("\n🔍 Testing Fantasy Teams API...")
    
    try:
        response = requests.get(url, params=params, timeout=10)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Success: {data.get('success')}")
            print(f"Count: {data.get('count')}")
            
            teams = data.get('teams', [])
            print(f"Total Teams: {len(teams)}")
            
            if teams:
                print("\n🏆 Team Details:")
                for team in teams:
                    print(f"\nTeam: {team.get('name')}")
                    print(f"  Owner: {team.get('owner')}")
                    print(f"  Sport: {team.get('sport')}")
                    print(f"  Players: {len(team.get('players', []))}")
                    
                    # Check player format
                    players = team.get('players', [])
                    if players and len(players) > 0:
                        first_player = players[0]
                        print(f"  First player type: {type(first_player)}")
                        if isinstance(first_player, dict):
                            print(f"  First player is an object with keys: {list(first_player.keys())}")
                        else:
                            print(f"  First player value: {first_player}")
        
        else:
            print(f"❌ Error: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Exception: {e}")

def test_api_health():
    url = "https://pleasing-determination-production.up.railway.app/"
    
    print("\n🔍 Testing API Health...")
    
    try:
        response = requests.get(url, timeout=5)
        print(f"Status Code: {response.status_code}")
        print(f"Response (first 500 chars): {response.text[:500]}")
    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    print("=" * 60)
    print("API TEST SCRIPT")
    print("=" * 60)
    
    test_api_health()
    test_fantasy_players_api()
    test_fantasy_teams_api()
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
