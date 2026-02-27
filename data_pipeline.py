import os
import requests
import json
from datetime import datetime
from typing import List, Dict, Any, Optional   # <-- Added missing typing imports

class UnifiedNBADataPipeline:
    def __init__(self, sleeper_league_id: str, rapidapi_key: str):
        self.sleeper_league_id = sleeper_league_id
        self.rapidapi_key = rapidapi_key
        self.sleeper_base = "https://api.sleeper.app/v1"
        self.tank01_host = "tank01-fantasy-stats.p.rapidapi.com"

    # ------------------- Sleeper -------------------
    def fetch_sleeper_data(self) -> Dict[str, Any]:
        """Fetch league rosters and player info from Sleeper"""
        league = requests.get(f"{self.sleeper_base}/league/{self.sleeper_league_id}").json()
        rosters = requests.get(f"{self.sleeper_base}/league/{self.sleeper_league_id}/rosters").json()
        players = requests.get(f"{self.sleeper_base}/players/nba").json()
        return {
            'league': league,
            'rosters': rosters,
            'players': players,
            'timestamp': datetime.now().isoformat()
        }

    # ------------------- Tank01 -------------------
    def fetch_tank01_data(self) -> Dict[str, Any]:
        """Fetch projections, ADP, injuries from Tank01"""
        headers = {
            'x-rapidapi-host': self.tank01_host,
            'x-rapidapi-key': self.rapidapi_key
        }
        # Get ADP
        adp_resp = requests.get(f"https://{self.tank01_host}/getNBAADP", headers=headers)
        adp = adp_resp.json().get('body', []) if adp_resp.ok else []

        # Get projections (7 days)
        proj_resp = requests.get(
            f"https://{self.tank01_host}/getNBAProjections",
            headers=headers,
            params={'numOfDays': '7', 'pts': '1', 'reb': '1.25', 'ast': '1.5', 'stl': '3', 'blk': '3', 'TOV': '-1'}
        )
        projections = proj_resp.json().get('body', {}).get('playerProjections', {}) if proj_resp.ok else {}

        # Get injuries
        inj_resp = requests.get(f"https://{self.tank01_host}/getNBAInjuryList", headers=headers)
        injuries = inj_resp.json().get('body', []) if inj_resp.ok else []

        return {
            'adp': adp,
            'projections': projections,
            'injuries': injuries,
            'timestamp': datetime.now().isoformat()
        }

    # ------------------- DraftKings (temporarily disabled) -------------------
    def fetch_draftkings_data(self) -> Dict[str, List]:
        """Disabled – returns empty salaries."""
        return {'salaries': []}

    # ------------------- Merging -------------------
    def merge_players(self, sleeper_players: Dict, tank01_data: Dict, dk_salaries: Dict) -> List[Dict]:
        """
        Merge player data from all sources into a unified list.
        """
        unified = []
        # Build lookup maps
        adp_map = {item['playerID']: item for item in tank01_data.get('adp', [])}
        proj_map = tank01_data.get('projections', {})
        inj_map = {item['playerID']: item for item in tank01_data.get('injuries', [])}
        dk_map = {item.get('name'): item for item in dk_salaries.get('salaries', [])}

        for sleeper_id, sleeper_player in sleeper_players.items():
            name = sleeper_player.get('full_name')
            if not name:
                continue

            # Simple name matching – improve later if needed
            tank01_match = None
            for pid, proj in proj_map.items():
                if proj.get('longName') and name in proj['longName']:
                    tank01_match = pid
                    break

            dk_match = dk_map.get(name)

            unified.append({
                'sleeper_id': sleeper_id,
                'name': name,
                'team': sleeper_player.get('team'),
                'position': sleeper_player.get('position'),
                'injury_status': 'Injured' if tank01_match and inj_map.get(tank01_match) else 'Healthy',
                'adp': adp_map.get(tank01_match, {}).get('overallADP') if tank01_match else None,
                'projection': proj_map.get(tank01_match, {}).get('fantasyPoints') if tank01_match else None,
                'salary_dk': dk_match.get('salary') if dk_match else None,
                # Add more fields as needed
            })
        return unified

    def save_unified_data(self, unified_players: List[Dict]):
        """Save the merged data to a JSON file."""
        filename = f"unified_players_{datetime.now().strftime('%Y%m%d')}.json"
        with open(filename, 'w') as f:
            json.dump(unified_players, f, indent=2)
        print(f"✅ Saved {len(unified_players)} unified players to {filename}")

    def run_daily_update(self):
        """Main orchestration method – call this once per day."""
        print(f"🚀 Starting unified update at {datetime.now()}")
        sleeper = self.fetch_sleeper_data()
        tank01 = self.fetch_tank01_data()
        dk = self.fetch_draftkings_data()
        unified = self.merge_players(sleeper['players'], tank01, dk)
        self.save_unified_data(unified)
        print("✅ Unified update complete!")

# ===== Standalone execution for testing =====
if __name__ == "__main__":
    # Replace with your actual Sleeper league ID and ensure RAPIDAPI_KEY is set
    pipeline = UnifiedNBADataPipeline(
        sleeper_league_id="YOUR_LEAGUE_ID",           # <-- CHANGE THIS
        rapidapi_key=os.getenv("RAPIDAPI_KEY", "cdd1cfc95bmsh3dea79dcd1be496p167ea1jsnb355ed1075ec")
    )
    pipeline.run_daily_update()
