#!/usr/bin/env python3
"""
Update NBA static data from CSV file.
Usage: python update_nba_static.py <csv_file> [--output OUTPUT_FILE]
"""

import csv
import sys
import argparse
import os
from datetime import datetime


def update_static_file(csv_file, output_file=None):
    """
    Update the static data file with new CSV data.

    Args:
        csv_file: Path to the input CSV file
        output_file: Path to output file (default: nba_static_data.py)

    Returns:
        bool: True if successful
    """
    try:
        # Read CSV data
        players = []
        with open(csv_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                players.append(row)

        print(f"📊 Read {len(players)} players from CSV")

        if len(players) == 0:
            print("❌ No players found in CSV")
            return False

        # Determine output file
        if output_file is None:
            output_file = "nba_static_data.py"

        # Generate new static table
        static_table = generate_static_table(players)

        # Generate new file content
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    lines = table_str.strip().split('\\n')
    
    # Find the header line
    header_idx = None
    for i, line in enumerate(lines):
        if 'Name' in line and 'Team' in line:
            header_idx = i
            break
    if header_idx is None:
        print("❌ Could not find header line in NBA_TABLE")
        return []
    
    header_line = lines[header_idx].strip()
    data_lines = lines[header_idx+1:]
    
    header_reader = csv.reader([header_line], delimiter='\\t')
    headers = next(header_reader)
    headers = [h.strip() for h in headers]
    
    header_map = {{
        'Name': 'name',
        'Team': 'team',
        'Pos': 'position',
        'Inj': 'injury',
        'g': 'games',
        'm/g': 'minutes_per_game',
        'p/g': 'points_per_game',
        '3/g': 'threes_per_game',
        'r/g': 'rebounds_per_game',
        'a/g': 'assists_per_game',
        's/g': 'steals_per_game',
        'b/g': 'blocks_per_game',
        'fg%': 'fg_pct',
        'fga/g': 'fga_per_game',
        'ft%': 'ft_pct',
        'fta/g': 'fta_per_game',
        'to/g': 'turnovers_per_game',
        'USG': 'usage'
    }}
    
    players = []
    for line in data_lines:
        if not line.strip():
            continue
        reader = csv.reader([line], delimiter='\\t')
        try:
            parts = next(reader)
        except StopIteration:
            continue
        if len(parts) != len(headers):
            parts = re.split(r'\\s{{2,}}', line.strip())
            if len(parts) != len(headers):
                print(f"⚠️ Skipping line – unexpected column count")
                continue
        
        player = {{}}
        for i, header in enumerate(headers):
            key = header_map.get(header, header.lower())
            raw_val = parts[i].strip() if i < len(parts) else ''
            
            if key in ['games', 'minutes_per_game', 'points_per_game', 'threes_per_game',
                       'rebounds_per_game', 'assists_per_game', 'steals_per_game',
                       'blocks_per_game', 'fga_per_game', 'fta_per_game', 'turnovers_per_game', 'usage']:
                try:
                    val = float(raw_val) if raw_val else 0.0
                except ValueError:
                    val = 0.0
            elif key in ['fg_pct', 'ft_pct']:
                if raw_val.startswith('.'):
                    raw_val = '0' + raw_val
                try:
                    val = float(raw_val) if raw_val else 0.0
                except ValueError:
                    val = 0.0
            else:
                val = raw_val
            
            player[key] = val
        
        # FanDuel fantasy points per game
        player['fantasy_points'] = (
            player.get('points_per_game', 0) +
            1.2 * player.get('rebounds_per_game', 0) +
            1.5 * player.get('assists_per_game', 0) +
            2 * player.get('steals_per_game', 0) +
            2 * player.get('blocks_per_game', 0) -
            player.get('turnovers_per_game', 0)
        )
        
        # Injury status mapping
        inj = str(player.get('injury', '')).lower()
        if 'inj' in inj or 'out' in inj:
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
    
    print(f"✅ Parsed {{len(players)}} players")
    return players

# Load once
NBA_PLAYERS_2026 = parse_nba_player_table(NBA_TABLE)

if __name__ == "__main__":
    print(f"Loaded {{len(NBA_PLAYERS_2026)}} NBA players from static table")
'''

        # Write the new file
        with open(output_file, "w") as f:
            f.write(new_content)

        print(f"✅ Successfully updated {output_file} with {len(players)} players")
        return True

    except Exception as e:
        print(f"❌ Error updating static file: {e}")
        return False


def generate_static_table(players):
    """Generate the static table string."""
    if not players:
        return ""

    # Get headers from first player
    headers = list(players[0].keys())

    lines = []
    # Add header
    lines.append("\t".join(headers))

    # Add each player
    for player in players:
        row = []
        for header in headers:
            val = player.get(header, "")
            # Clean up values
            if isinstance(val, float):
                if header in ["fg%", "ft%"]:
                    # Format as .XXX
                    val = f".{str(val).split('.')[1][:3]}"
                else:
                    val = f"{val:.2f}" if val != int(val) else str(int(val))
            row.append(str(val))
        lines.append("\t".join(row))

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update NBA static data")
    parser.add_argument("csv_file", help="Path to CSV file")
    parser.add_argument(
        "--output", "-o", help="Output file path", default="nba_static_data.py"
    )

    args = parser.parse_args()

    success = update_static_file(args.csv_file, args.output)
    sys.exit(0 if success else 1)
