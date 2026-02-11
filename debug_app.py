import re

with open('app.py', 'r') as f:
    lines = f.readlines()

print("🔍 DEBUGGING app.py FOR LIMITING ISSUES")
print("=" * 60)

# Look for limiting patterns
patterns = [
    (r'\[:(\d+)\]', 'Slicing to first X items'),
    (r'\.slice\(', 'JavaScript slice method'),
    (r'outcomes\[:', 'Outcomes array slicing'),
    (r'data_source = .*\[:', 'Data source slicing'),
    (r'players_data.*\[:', 'Player data slicing'),
]

found_issues = []

for i, line in enumerate(lines, 1):
    line = line.rstrip()
    for pattern, desc in patterns:
        if re.search(pattern, line):
            found_issues.append((i, line, desc))
            break

if found_issues:
    print("🚨 FOUND LIMITING CODE:")
    for i, line, desc in found_issues:
        print(f"Line {i}: {desc}")
        print(f"   {line}")
else:
    print("✅ No obvious limiting code found")
    print("Check cache or response formatting")

print("\n" + "=" * 60)
print("📋 Checking data flow in get_predictions_outcome...")

# Find the function
func_start = None
for i, line in enumerate(lines):
    if 'def get_predictions_outcome' in line:
        func_start = i
        break

if func_start:
    print(f"Function starts at line {func_start}")
    # Show key parts
    in_func = False
    for i in range(func_start, min(func_start + 100, len(lines))):
        line = lines[i].rstrip()
        if 'def ' in line and i != func_start:
            break
        if 'data_source = ' in line or 'outcomes = ' in line or 'return jsonify' in line:
            print(f"Line {i}: {line}")
