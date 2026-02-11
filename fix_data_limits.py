#!/usr/bin/env python3
"""
Fix all data source limits in app.py
"""
import re

with open('app.py', 'r') as f:
    lines = f.readlines()

print("🔧 FIXING DATA LIMITS IN app.py")
print("=" * 60)

# Track changes
changes = []

# Fix specific lines
fixes = [
    (2414, "players_data_list[:50]", "players_data_list[:100]"),
    (2673, "nfl_players_data[:5]", "nfl_players_data[:30]"),
    (2675, "mlb_players_data[:50]", "mlb_players_data[:40]"),
    (2677, "nhl_players_data[:50]", "nhl_players_data[:40]"),
    (3575, "players_data_list[:100]", "players_data_list[:150]"),
    (3577, "nfl_players_data[:10]", "nfl_players_data[:50]"),
    (3579, "mlb_players_data[:60]", "mlb_players_data[:50]"),
    (3581, "nhl_players_data[:50]", "nhl_players_data[:50]"),  # Already OK
    (3953, "nfl_players_data[:20]", "nfl_players_data[:40]"),
    (3959, "data_source[:8]", "data_source[:20]"),
    (4029, "nfl_players_data[:15]", "nfl_players_data[:30]"),
    (4919, "players_data_list[:70]", "players_data_list[:100]"),
    (4921, "nfl_players_data[:70]", "nfl_players_data[:50]"),
    (4923, "mlb_players_data[:70]", "mlb_players_data[:50]"),
    (4925, "nhl_players_data[:70]", "nhl_players_data[:50]"),
    (5347, "nfl_players_data[:50]", "nfl_players_data[:50]"),  # OK
]

for line_num, old, new in fixes:
    if line_num <= len(lines):
        old_line = lines[line_num-1].rstrip()
        if old in old_line:
            new_line = old_line.replace(old, new)
            lines[line_num-1] = new_line + '\n'
            changes.append((line_num, old, new))
            print(f"Line {line_num}: {old} → {new}")

# Also check for generic [:10] on player data lines
for i, line in enumerate(lines):
    if any(pattern in line for pattern in ['players_data_list[:', 'nfl_players_data[:', 'mlb_players_data[:', 'nhl_players_data[:']):
        # Find [:X] pattern
        match = re.search(r'\[:(\d+)\]', line)
        if match:
            limit = int(match.group(1))
            if limit < 30:
                new_limit = 50
                new_line = re.sub(r'\[:(\d+)\]', f'[:{new_limit}]', line)
                lines[i] = new_line
                changes.append((i+1, f'[:{limit}]', f'[:{new_limit}]'))
                print(f"Line {i+1}: Increased limit from {limit} to {new_limit}")

# Write back
with open('app.py', 'w') as f:
    f.writelines(lines)

print(f"\n✅ Made {len(changes)} changes")
print("=" * 60)

# Verify the get_predictions_outcome function
print("\n🔍 Checking get_predictions_outcome function...")
func_found = False
for i, line in enumerate(lines):
    if 'def get_predictions_outcome' in line:
        func_found = True
        print(f"\nFunction at line {i+1}:")
    if func_found and i >= i and i < i+50:
        if 'data_source = ' in line or 'outcomes = ' in line or 'return jsonify' in line:
            print(f"  Line {i+1}: {line.rstrip()}")

