# quick_test.py
import json
from nba_static_data import NBA_PLAYERS_2026

print("=== NBA Static Data Validation ===")
print(f"Total players: {len(NBA_PLAYERS_2026)}")

# Check data quality
players_with_stats = [p for p in NBA_PLAYERS_2026 if p.get('games', 0) > 0]
print(f"Players with games played: {len(players_with_stats)}")

# Check injury status distribution
injury_counts = {}
for p in NBA_PLAYERS_2026:
    status = p.get('injury_status', 'unknown')
    injury_counts[status] = injury_counts.get(status, 0) + 1

print("\nInjury Status Distribution:")
for status, count in injury_counts.items():
    print(f"  {status}: {count}")

# Check fantasy points distribution
fp_values = [p.get('fantasy_points', 0) for p in NBA_PLAYERS_2026]
print(f"\nFantasy Points Range:")
print(f"  Min: {min(fp_values):.1f}")
print(f"  Max: {max(fp_values):.1f}")
print(f"  Avg: {sum(fp_values)/len(fp_values):.1f}")

# Verify sample data
print("\nSample Players:")
for p in NBA_PLAYERS_2026[:5]:
    print(f"  {p['name']}: {p['games']}g, {p['pts_per_game']:.1f}ppg, {p['fantasy_points']:.1f}fp")
