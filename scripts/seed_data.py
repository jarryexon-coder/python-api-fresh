#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

def find_players_file():
    """Search for players_data_comprehensive_fixed.json in likely locations."""
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    candidates = [
        project_root / "players_data_comprehensive_fixed.json",   # root
        project_root / "data" / "players_data_comprehensive_fixed.json", # data/
        script_dir / "players_data_comprehensive_fixed.json",     # scripts/
    ]
    
    for path in candidates:
        if path.exists():
            return path
    return None

def seed(year: str):
    print(f"Seeding database for year {year}...")
    
    players_file = find_players_file()
    if not players_file:
        print("ERROR: Could not find players_data_comprehensive_fixed.json in any expected location.")
        return
    
    print(f"Found players file at: {players_file}")
    with open(players_file) as f:
        players = json.load(f)
    print(f"Loaded {len(players)} players")
    # TODO: Insert into your database (if you have one)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", default="2026")
    args = parser.parse_args()
    seed(args.year)
