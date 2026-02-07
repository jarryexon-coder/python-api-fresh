import re

with open('app.py', 'r') as f:
    content = f.read()

# Find the get_fantasy_teams function
pattern = r'@app\.route\(\'/api/fantasy/teams\'\)\s+def get_fantasy_teams\(\):(.*?)(?=\n@app\.route|\ndef |\nif __name__)'
match = re.search(pattern, content, re.DOTALL)

if match:
    print("Found existing get_fantasy_teams function")
    
    # Replace with working version
    fixed_function = '''@app.route('/api/fantasy/teams')
def get_fantasy_teams():
    """FIXED: Get fantasy teams with real data"""
    try:
        sport = flask_request.args.get('sport', 'nba')
        
        print(f"🎯 GET /api/fantasy/teams: sport={sport}")
        
        cache_key = get_cache_key('fantasy_teams', {'sport': sport})
        if cache_key in general_cache and is_cache_valid(general_cache[cache_key]):
            print(f"✅ Serving fantasy teams from cache")
            return jsonify(general_cache[cache_key]['data'])
        
        # Load real fantasy teams data
        if fantasy_teams_data:
            # Filter by sport if specified
            if sport and sport.lower() != 'all':
                filtered_teams = [
                    team for team in fantasy_teams_data 
                    if team.get('sport', '').lower() == sport.lower()
                ]
            else:
                filtered_teams = fantasy_teams_data
            
            response_data = {
                'success': True,
                'teams': filtered_teams[:50],
                'count': len(filtered_teams),
                'timestamp': datetime.utcnow().isoformat(),
                'sport': sport,
                'is_real_data': True,
                'has_data': len(filtered_teams) > 0,
                'message': f'Found {len(filtered_teams)} fantasy teams'
            }
        else:
            # Fallback if no data loaded
            response_data = {
                'success': True,
                'teams': [],
                'count': 0,
                'timestamp': datetime.utcnow().isoformat(),
                'sport': sport,
                'is_real_data': False,
                'has_data': False,
                'message': 'No fantasy teams data loaded'
            }
        
        # Cache the response
        general_cache[cache_key] = {
            'data': response_data,
            'timestamp': time.time()
        }
        
        print(f"✅ Fantasy teams: {response_data['count']} teams for {sport}")
        return jsonify(response_data)
        
    except Exception as e:
        print(f"❌ Error in /api/fantasy/teams: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e),
            'teams': [],
            'count': 0,
            'is_real_data': False,
            'has_data': False
        })'''

    # Replace the function
    new_content = content.replace(match.group(0), fixed_function)
    
    with open('app.py', 'w') as f:
        f.write(new_content)
    
    print("✅ Updated /api/fantasy/teams endpoint")
else:
    print("❌ Could not find get_fantasy_teams function")
