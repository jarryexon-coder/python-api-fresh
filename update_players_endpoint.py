import re

with open('app.py', 'r') as f:
    content = f.read()

# Find the get_players function
pattern = r'@app\.route\(\'/api/players\'\)\s+def get_players\(\):(.*?)(?=\n@app\.route|\ndef |\nif __name__)'
match = re.search(pattern, content, re.DOTALL)

if match:
    print("Found existing get_players function:")
    print(match.group(0)[:500] + "..." if len(match.group(0)) > 500 else match.group(0))
    
    # Replace with fixed version
    fixed_function = '''@app.route('/api/players')
def get_players():
    """Get players with sport filtering - FIXED VERSION"""
    try:
        sport = flask_request.args.get('sport', 'nba').lower()
        
        # FIX: Handle limit parameter properly (React sometimes sends object)
        limit_param = flask_request.args.get('limit', '50')
        try:
            # Try to convert to int, default to 50 if fails
            if isinstance(limit_param, str) and limit_param.isdigit():
                limit = int(limit_param)
            else:
                limit = 50
        except:
            limit = 50
        
        print(f"🎯 GET /api/players: sport={sport}, limit={limit}")
        
        # Get appropriate data source
        if sport == 'nba':
            data_source = players_data_list
        elif sport == 'nfl':
            data_source = nfl_players_data
        elif sport == 'mlb':
            data_source = mlb_players_data
        elif sport == 'nhl':
            data_source = nhl_players_data
        else:
            # For 'all' or unspecified, combine top from each
            data_source = []
            top_n = min(limit // 4, 20) if limit else 20
            data_source.extend(players_data_list[:top_n])
            data_source.extend(nfl_players_data[:top_n])
            data_source.extend(mlb_players_data[:top_n])
            data_source.extend(nhl_players_data[:top_n])
        
        # Format players data
        formatted_players = []
        for i, player in enumerate(data_source[:limit]):
            player_name = player.get('name') or player.get('playerName') or f'Player_{i}'
            
            formatted_players.append({
                'id': player.get('id', f'player-{sport}-{i}'),
                'name': player_name,
                'team': player.get('teamAbbrev') or player.get('team', 'Unknown'),
                'position': player.get('position') or player.get('pos', 'Unknown'),
                'sport': sport.upper(),
                'stats': {
                    'points': player.get('points') or player.get('pts', 0),
                    'rebounds': player.get('rebounds') or player.get('reb', 0),
                    'assists': player.get('assists') or player.get('ast', 0),
                    'fantasy_score': player.get('fantasyScore') or player.get('fp', 0),
                    'season_average': player.get('seasonAvg', 0),
                    'last_5_average': player.get('last5Avg', 0)
                },
                'injury_status': player.get('injuryStatus', 'healthy'),
                'value_score': player.get('valueScore', 0),
                'trend': player.get('trend', 'stable'),
                'is_real_data': True
            })
        
        response = {
            'success': True,
            'players': formatted_players,
            'count': len(formatted_players),
            'timestamp': datetime.utcnow().isoformat(),
            'sport': sport,
            'message': f'Found {len(formatted_players)} players'
        }
        
        print(f"✅ Players endpoint: {len(formatted_players)} players for {sport}")
        return jsonify(response)
        
    except Exception as e:
        print(f"❌ Error in /api/players: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e),
            'players': [],
            'count': 0
        })'''

    # Replace the function in the content
    new_content = content.replace(match.group(0), fixed_function)
    
    with open('app.py', 'w') as f:
        f.write(new_content)
    
    print("✅ Updated /api/players endpoint")
else:
    print("❌ Could not find get_players function")
