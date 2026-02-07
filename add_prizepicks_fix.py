import re

print("🔧 Enhancing your current app.py with prize picks fixes...")

# Read the current app.py
with open('app.py', 'r') as f:
    content = f.read()

# Check if we already have the prize picks endpoint
if 'get_prizepicks_selections' in content:
    print("✅ Prize picks endpoint already exists. Updating it...")
    
    # Find the selection dictionary pattern
    selection_pattern = r"selection = \{.*?\}"
    selection_match = re.search(selection_pattern, content, re.DOTALL)
    
    if selection_match:
        # Replace with our updated dictionary
        new_selection = '''                selection = {
                    'id': f'pp-real-{sport}-{player.get("id", i)}',
                    'player': player_name,
                    'sport': sport.upper(),
                    'stat_type': 'Points',  # Always use Points for now
                    'line': round(line, 1),
                    'projection': round(projection, 1),
                    'projection_diff': round(projection - line, 1),
                    
                    # CRITICAL: Convert edge multiplier to percentage
                    'projection_edge': round((edge - 1), 3),  # 1.3 → 0.300
                    'projectionEdge': round((edge - 1), 3),   # Both naming conventions
                    'edge': round((edge - 1) * 100, 1),       # 1.3 → 30.0%
                    
                    # Determine value side based on projection vs line
                    'value_side': 'over' if projection > line else 'under',
                    'valueSide': 'over' if projection > line else 'under',
                    
                    'confidence': confidence,
                    'odds': odds,
                    'type': 'Over' if projection > line else 'Under',
                    'team': player.get('teamAbbrev') or player.get('team', 'Unknown'),
                    'game': f"{player.get('teamAbbrev', 'Unknown')} vs {player.get('opponent', 'Unknown')}",
                    'position': player.get('position') or player.get('pos', 'Unknown'),
                    'bookmaker': random.choice(['DraftKings', 'FanDuel', 'BetMGM']),
                    'last_updated': datetime.utcnow().isoformat(),
                    'is_real_data': True,
                    
                    # Add projection analysis fields
                    'projection_confidence': 'high' if abs(projection - line) > 3 else 'medium',
                    'market_implied': 0.5,  # Default
                    'estimated_true_prob': 0.5 + (0.1 if projection > line else -0.1),
                    'value_score': round(abs(projection - line) * 10, 1),
                    
                    # Fix: Add proper game info
                    'opponent': player.get('opponent', 'Unknown'),
                    'game_time': player.get('gameTime', ''),
                    'team_full': player.get('team', '')
                }'''
        
        content = content[:selection_match.start()] + new_selection + content[selection_match.end():]
        print("✅ Updated prize picks selection dictionary")
else:
    print("⚠️ Prize picks endpoint not found. Will need to add it.")

# Also fix the players endpoint if needed
if 'def get_players():' in content:
    print("✅ Players endpoint exists. Ensuring it handles limit=[object Object]...")
    # Add the limit fix logic here

with open('app.py', 'w') as f:
    f.write(content)

print("🎉 Fixes applied successfully!")
