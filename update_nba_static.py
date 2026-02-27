# update_nba_static.py
#!/usr/bin/env python3
"""
Update NBA static data file from CSV source.
Usage: python update_nba_static.py <csv_file> [--output OUTPUT_FILE]
"""

import csv
import re
import sys
import argparse
from datetime import datetime
from typing import List, Dict, Optional

def auto_download():
    """Auto-download the latest CSV file."""
    import requests
    import os
    
    data_url = os.environ.get('NBA_DATA_URL')
    if not data_url:
        # You can hardcode a URL temporarily for testing
        data_url = "https://your-actual-data-source.com/nba-stats.csv"
        print("⚠️  NBA_DATA_URL not set, using hardcoded URL")
    
    try:
        print(f"📥 Auto-downloading from {data_url}")
        response = requests.get(data_url, timeout=30)
        response.raise_for_status()
        
        csv_path = '/tmp/nba_stats_latest.csv'
        with open(csv_path, 'wb') as f:
            f.write(response.content)
        
        print(f"✅ Downloaded {len(response.content)} bytes")
        return csv_path
    except Exception as e:
        print(f"❌ Download failed: {e}")
        return None

def validate_csv_structure(csv_file: str) -> bool:
    """Validate that the CSV has the required columns."""
    required_columns = {'Name', 'Team', 'Pos', 'g', 'min', 'pts', '3', 'reb', 
                       'ast', 'stl', 'blk', 'fg%', 'fga', 'ft%', 'fta', 'to', 'USG'}
    
    with open(csv_file, 'r') as f:
        reader = csv.reader(f)
        headers = next(reader)
        headers_set = {h.strip() for h in headers}
        
        missing = required_columns - headers_set
        if missing:
            print(f"❌ Missing required columns: {missing}")
            return False
        
        print(f"✅ CSV validation passed - found {len(headers)} columns")
        return True

def format_percentage(value) -> str:
    """Format percentage values consistently."""
    if isinstance(value, str):
        value = value.strip()
        if value.startswith('.'):
            return value
        try:
            float_val = float(value)
            return f".{str(float_val).split('.')[1]}" if float_val < 1 else value
        except ValueError:
            return value
    elif isinstance(value, (int, float)):
        if value < 1:
            # Convert to format like .577
            str_val = f"{value:.3f}"
            return '.' + str_val.split('.')[1]
        return str(value)
    return str(value)

def generate_static_table(players: List[Dict]) -> str:
    """Generate the static table string for nba_static_data.py."""
    lines = []
    
    # Add header
    headers = ['Round', 'Rank', 'Value', 'Name', 'Team', 'Pos', 'Inj', 'g', 
               'min', 'pts', '3', 'reb', 'ast', 'stl', 'blk', 'fg%', 'fga', 
               'ft%', 'fta', 'to', 'USG', 'pV', '3V', 'rV', 'aV', 'sV', 'bV', 
               'fg%V', 'ft%V', 'toV']
    
    lines.append('\t'.join(headers))
    
    # Add each player
    for player in players:
        row = []
        for header in headers:
            key = header.lower()
            if key == 'name':
                val = player.get('Name', '')
            elif key == 'team':
                val = player.get('Team', '')
            elif key == 'pos':
                val = player.get('Pos', '')
            elif key == 'inj':
                val = player.get('Inj', '')
            else:
                val = player.get(header, player.get(key, ''))
            
            # Format specific fields
            if header in ['fg%', 'ft%']:
                val = format_percentage(val)
            elif header in ['Value', 'USG', 'pV', '3V', 'rV', 'aV', 'sV', 'bV', 'fg%V', 'ft%V', 'toV']:
                try:
                    val = f"{float(val):.2f}"
                except (ValueError, TypeError):
                    val = str(val)
            
            row.append(str(val))
        
        lines.append('\t'.join(row))
    
    return '\n'.join(lines)

def update_static_file(csv_file: str, output_file: Optional[str] = None) -> bool:
    """
    Update the static data file with new CSV data.
    
    Args:
        csv_file: Path to the input CSV file
        output_file: Path to output file (default: updates nba_static_data.py)
    
    Returns:
        bool: True if successful
    """
    try:
        # Validate CSV structure
        if not validate_csv_structure(csv_file):
            return False
        
        # Read CSV data
        players = []
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                players.append(row)
        
        print(f"📊 Read {len(players)} players from CSV")
        
        # Generate new static table
        static_table = generate_static_table(players)
        
        # Determine output file
        if output_file is None:
            output_file = 'nba_static_data.py'
        
        # Read existing file to preserve imports and functions
        try:
            with open(output_file, 'r') as f:
                existing_content = f.read()
        except FileNotFoundError:
            existing_content = None
        
        # Generate new file content
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        new_content = f'''# nba_static_data.py
# Auto-generated on {timestamp}
# Contains {len(players)} NBA players

import csv
import io
import re
from typing import List, Dict

# ===== 2026 NBA PLAYER STATS ({len(players)} players) =====
NBA_TABLE = """
{static_table}
"""

def parse_nba_player_table(table_str: str) -> List[Dict]:
    """Parse the tab-separated NBA player table using csv.reader."""
    # Remove leading/trailing whitespace and split into lines
    lines = table_str.strip().split('\\n')
    
    # Find the header line (contains 'Name' and 'Team')
    header_idx = None
    for i, line in enumerate(lines):
        if 'Name' in line and 'Team' in line:
            header_idx = i
            break
    if header_idx is None:
        print("❌ Could not find header line in NBA_TABLE")
        return []
    
    # Use csv.reader with tab delimiter
    header_line = lines[header_idx].strip()
    data_lines = lines[header_idx+1:]
    
    # Create a CSV reader that treats tabs as delimiters
    header_reader = csv.reader([header_line], delimiter='\\t')
    headers = next(header_reader)
    headers = [h.strip() for h in headers]  # clean up spaces
    
    # Map headers to internal keys
    header_map = {{
        'Name': 'name',
        'Team': 'team',
        'Pos': 'position',
        'Inj': 'injury',
        'g': 'games',
        'min': 'minutes',
        'pts': 'points',
        '3': 'threes',
        'reb': 'rebounds',
        'ast': 'assists',
        'stl': 'steals',
        'blk': 'blocks',
        'fg%': 'fg_pct',
        'fga': 'fga',
        'ft%': 'ft_pct',
        'fta': 'fta',
        'to': 'turnovers',
        'USG': 'usage',
        'pV': 'pV',
        '3V': '3V',
        'rV': 'rV',
        'aV': 'aV',
        'sV': 'sV',
        'bV': 'bV',
        'fg%V': 'fg%V',
        'ft%V': 'ft%V',
        'toV': 'toV'
    }}
    
    players = []
    for line in data_lines:
        if not line.strip():
            continue
        # Use csv.reader for this line
        reader = csv.reader([line], delimiter='\\t')
        try:
            parts = next(reader)
        except StopIteration:
            continue
        if len(parts) != len(headers):
            # Fallback: try splitting by multiple spaces
            parts = re.split(r'\\s{{2,}}', line.strip())
            if len(parts) != len(headers):
                print(f"⚠️ Skipping line – unexpected column count: {{len(parts)}} vs {{len(headers)}}")
                continue
        
        player = {{}}
        for i, header in enumerate(headers):
            key = header_map.get(header, header.lower())
            raw_val = parts[i].strip() if i < len(parts) else ''
            # Remove any trailing $ if present
            if raw_val.endswith('$'):
                raw_val = raw_val[:-1]
            
            # Convert numeric fields
            if key in ['games', 'points', 'threes', 'rebounds', 'assists', 'steals', 'blocks',
                       'fga', 'fta', 'turnovers', 'minutes', 'usage']:
                # Remove commas and convert
                raw_val = raw_val.replace(',', '')
                try:
                    val = float(raw_val) if raw_val else 0.0
                except ValueError:
                    val = 0.0
            elif key in ['fg_pct', 'ft_pct']:
                # Handle percentage strings like .577
                if raw_val.startswith('.'):
                    raw_val = '0' + raw_val
                try:
                    val = float(raw_val) if raw_val else 0.0
                except ValueError:
                    val = 0.0
            else:
                val = raw_val
            
            player[key] = val
        
        # Per‑game averages
        g = player.get('games', 1)
        if g == 0:
            g = 1  # avoid division by zero
        player['pts_per_game'] = player.get('points', 0) / g
        player['reb_per_game'] = player.get('rebounds', 0) / g
        player['ast_per_game'] = player.get('assists', 0) / g
        player['stl_per_game'] = player.get('steals', 0) / g
        player['blk_per_game'] = player.get('blocks', 0) / g
        player['to_per_game'] = player.get('turnovers', 0) / g
        
        # FanDuel fantasy points per game
        player['fantasy_points'] = (
            player['pts_per_game'] +
            1.2 * player['reb_per_game'] +
            1.5 * player['ast_per_game'] +
            2 * player['stl_per_game'] +
            2 * player['blk_per_game'] -
            player['to_per_game']
        )
        
        # Injury status mapping
        inj = str(player.get('injury', '')).lower()
        if 'inj' in inj or 'out' in inj or 'off inj' in inj:
            player['injury_status'] = 'injured'
        elif 'q' in inj or 'questionable' in inj:
            player['injury_status'] = 'questionable'
        elif 'd' in inj or 'day' in inj or 'probable' in inj:
            player['injury_status'] = 'day-to-day'
        elif 'x' in inj:
            player['injury_status'] = 'out'
        elif 'susp' in inj:
            player['injury_status'] = 'suspended'
        else:
            player['injury_status'] = 'healthy'
        
        players.append(player)
    
    print(f"✅ Parsed {{len(players)}} players from NBA_TABLE")
    if players:
        print(f"   Sample: {{players[0].get('name')}} – {{players[0].get('team')}} – FP: {{players[0].get('fantasy_points'):.1f}}")
    return players

# Load once
NBA_PLAYERS_2026 = parse_nba_player_table(NBA_TABLE)

if __name__ == "__main__":
    print(f"Loaded {{len(NBA_PLAYERS_2026)}} NBA players from static table")
    # Print top 5 players by fantasy points
    top_players = sorted(NBA_PLAYERS_2026, key=lambda x: x.get('fantasy_points', 0), reverse=True)[:5]
    print("\\nTop 5 Players by Fantasy Points:")
    for p in top_players:
        print(f"  {{p['name']}} ({{p['team']}}): {{p['fantasy_points']:.1f}} FP/game")
'''
        
        # Write the new file
        with open(output_file, 'w') as f:
            f.write(new_content)
        
        print(f"✅ Successfully updated {output_file} with {len(players)} players")
        return True
        
    except Exception as e:
        print(f"❌ Error updating static file: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Update NBA static data file')
    parser.add_argument('csv_file', help='Path to CSV file with NBA stats')
    parser.add_argument('--output', '-o', help='Output file path (default: nba_static_data.py)')
    
    args = parser.parse_args()
    
    success = update_static_file(args.csv_file, args.output)
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
