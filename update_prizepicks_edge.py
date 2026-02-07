import re

with open('app.py', 'r') as f:
    content = f.read()

# Find the edge calculation section in prizepicks/selections
# Look for the part that calculates edge
lines = content.split('\n')
for i, line in enumerate(lines):
    if 'edge =' in line and 'edge_pct * 100' in content:
        # Found an edge calculation
        print(f"Found edge calculation at line {i}: {line}")
        
        # Update to use consistent 2.6% format (which we agreed to keep)
        # We'll make sure it's calculating correctly
        if 'edge = float(round(edge_pct * 100, 1))' in line:
            print("✅ Edge calculation already correct (2.6% format)")
        else:
            # Update the line
            lines[i] = '                \'edge\': float(round(edge_pct * 100, 1)),  # 2.6% format'
            print("Updated edge calculation")
            
            # Write back
            with open('app.py', 'w') as f:
                f.write('\n'.join(lines))
            
            print("✅ Updated edge calculation to 2.6% format")
        break
