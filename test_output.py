# nba_static_data.py
# Auto-generated on 2026-02-27 15:02:54
# Contains 1 NBA players

import csv
import io
import re
from typing import List, Dict

# ===== 2026 NBA PLAYER STATS (1 players) =====
NBA_TABLE = """
Round	Rank	Value	Name	Team	Pos	Inj	g	m/g	p/g	3/g	r/g	a/g	s/g	b/g	fg%	fga/g	ft%	fta/g	to/g	USG	pV	3V	rV	aV	sV	bV	fg%V	ft%V	toV
1	1	1.15	Nikola Jokic	DEN	C		43	34.2	28.8	2.0	12.5	10.4	1.4	0.8	.577	17.5	.830	8.0	3.7	31.4	2.06	0.32	2.80	3.20	0.86	0.11	2.39	0.60	-1.99
"""

def parse_nba_player_table(table_str: str) -> List[Dict]:
    """Parse the tab-separated NBA player table using csv.reader."""
    lines = table_str.strip().split('\n')
    
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
    
    header_reader = csv.reader([header_line], delimiter='\t')
    headers = next(header_reader)
    headers = [h.strip() for h in headers]
    
    header_map = {
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
    }
    
    players = []
    for line in data_lines:
        if not line.strip():
            continue
        reader = csv.reader([line], delimiter='\t')
        try:
            parts = next(reader)
        except StopIteration:
            continue
        if len(parts) != len(headers):
            parts = re.split(r'\s{2,}', line.strip())
            if len(parts) != len(headers):
                print(f"⚠️ Skipping line – unexpected column count")
                continue
        
        player = {}
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
    
    print(f"✅ Parsed {len(players)} players")
    return players

# Load once
NBA_PLAYERS_2026 = parse_nba_player_table(NBA_TABLE)

if __name__ == "__main__":
    print(f"Loaded {len(NBA_PLAYERS_2026)} NBA players from static table")
