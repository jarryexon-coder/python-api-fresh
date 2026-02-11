#!/usr/bin/env python3
"""
Update player data with realistic, current statistics
"""
import json
import random
from datetime import datetime, timedelta
import os

def update_player_data():
    print("🔄 Updating player data...")
    
    # Current NBA players (update as needed)
    current_nba_players = [
        {"name": "LeBron James", "team": "LAL", "position": "SF"},
        {"name": "Stephen Curry", "team": "GSW", "position": "PG"},
        {"name": "Nikola Jokic", "team": "DEN", "position": "C"},
        {"name": "Giannis Antetokounmpo", "team": "MIL", "position": "PF"},
        {"name": "Luka Doncic", "team": "DAL", "position": "PG"},
        {"name": "Jayson Tatum", "team": "BOS", "position": "SF"},
        {"name": "Kevin Durant", "team": "PHX", "position": "SF"},
        {"name": "Joel Embiid", "team": "PHI", "position": "C"},
        {"name": "Shai Gilgeous-Alexander", "team": "OKC", "position": "PG"},
        {"name": "Anthony Edwards", "team": "MIN", "position": "SG"},
        {"name": "Devin Booker", "team": "PHX", "position": "SG"},
        {"name": "Damian Lillard", "team": "MIL", "position": "PG"},
        {"name": "Donovan Mitchell", "team": "CLE", "position": "SG"},
        {"name": "Anthony Davis", "team": "LAL", "position": "PF"},
        {"name": "Tyrese Haliburton", "team": "IND", "position": "PG"}
    ]
    
    # Generate realistic player data
    updated_players = []
    
    for i, player in enumerate(current_nba_players):
        # Realistic fantasy point ranges for NBA players
        base_fp = random.uniform(30, 70)
        
        # Add some variation
        projection = round(base_fp + random.uniform(-5, 5), 1)
        actual = round(projection + random.uniform(-15, 15), 1)
        
        # Some should have incorrect predictions
        if random.random() < 0.3:  # 30% chance of incorrect
            actual = round(projection + random.uniform(-25, -10) if random.random() > 0.5 else random.uniform(10, 25), 1)
        
        player_data = {
            "id": f"player_{i+1}",
            "name": player["name"],
            "playerName": player["name"],
            "team": player["team"],
            "position": player["position"],
            "projection": projection,
            "projFP": projection,
            "fantasyScore": actual,
            "fp": actual,
            "projectionConfidence": random.randint(65, 85),
            "lastUpdated": datetime.now().isoformat(),
            "gamesPlayed": random.randint(10, 60),
            "avgMinutes": round(random.uniform(28, 38), 1),
            "injuryStatus": "Active" if random.random() > 0.1 else "Day-to-day",
            "trend": random.choice(["up", "down", "neutral"])
        }
        
        updated_players.append(player_data)
    
    # Save to file
    output_file = "players_data.json"
    with open(output_file, 'w') as f:
        json.dump(updated_players, f, indent=2)
    
    print(f"✅ Updated {len(updated_players)} players in {output_file}")
    print(f"📊 Sample player: {updated_players[0]['name']} - Proj: {updated_players[0]['projection']}, Actual: {updated_players[0]['fantasyScore']}")
    
    return updated_players

def create_realistic_mock_data():
    """Create more realistic mock data for other sports"""
    sports_data = {
        "nfl": [
            {"name": "Patrick Mahomes", "team": "KC", "position": "QB"},
            {"name": "Christian McCaffrey", "team": "SF", "position": "RB"},
            {"name": "Tyreek Hill", "team": "MIA", "position": "WR"},
            {"name": "Josh Allen", "team": "BUF", "position": "QB"},
            {"name": "Justin Jefferson", "team": "MIN", "position": "WR"}
        ],
        "mlb": [
            {"name": "Shohei Ohtani", "team": "LAD", "position": "DH/SP"},
            {"name": "Aaron Judge", "team": "NYY", "position": "RF"},
            {"name": "Ronald Acuña Jr.", "team": "ATL", "position": "RF"},
            {"name": "Mookie Betts", "team": "LAD", "position": "RF"},
            {"name": "Freddie Freeman", "team": "LAD", "position": "1B"}
        ],
        "nhl": [
            {"name": "Connor McDavid", "team": "EDM", "position": "C"},
            {"name": "Nathan MacKinnon", "team": "COL", "position": "C"},
            {"name": "Auston Matthews", "team": "TOR", "position": "C"},
            {"name": "David Pastrnak", "team": "BOS", "position": "RW"},
            {"name": "Nikita Kucherov", "team": "TB", "position": "RW"}
        ]
    }
    
    for sport, players in sports_data.items():
        filename = f"{sport}_players_data.json"
        sport_players = []
        
        for i, player in enumerate(players):
            # Sport-specific ranges
            if sport == "nfl":
                proj = random.uniform(15, 35)
                actual = proj + random.uniform(-10, 10)
            elif sport == "mlb":
                proj = random.uniform(8, 25)
                actual = proj + random.uniform(-7, 7)
            elif sport == "nhl":
                proj = random.uniform(5, 20)
                actual = proj + random.uniform(-5, 5)
            else:
                proj = random.uniform(10, 30)
                actual = proj + random.uniform(-8, 8)
            
            player_data = {
                "id": f"{sport}_player_{i+1}",
                "name": player["name"],
                "playerName": player["name"],
                "team": player["team"],
                "position": player["position"],
                "projection": round(proj, 1),
                "projFP": round(proj, 1),
                "fantasyScore": round(actual, 1),
                "fp": round(actual, 1),
                "projectionConfidence": random.randint(60, 80),
                "lastUpdated": datetime.now().isoformat(),
                "sport": sport
            }
            
            sport_players.append(player_data)
        
        with open(filename, 'w') as f:
            json.dump(sport_players, f, indent=2)
        
        print(f"✅ Created {filename} with {len(sport_players)} players")

if __name__ == "__main__":
    update_player_data()
    create_realistic_mock_data()
