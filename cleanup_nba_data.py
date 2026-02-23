# cleanup_nba_data.py
import re

def clean_raw_table(raw_text):
    # Split into lines
    lines = raw_text.strip().split('\n')
    
    # Find the start of the actual data (skip shell prompts and stray lines)
    start_idx = 0
    for i, line in enumerate(lines):
        if re.match(r'^\d+\s+\d+\s+-?\d+\.', line):
            start_idx = i
            break
    
    data_lines = lines[start_idx:]
    
    # Merge lines that belong to the same player
    merged = []
    current = []
    expected_fields = 29   # number of columns in header
    
    for line in data_lines:
        line = line.strip()
        if not line:
            continue
        
        # If line starts with a number (Round) it's likely a new player
        if re.match(r'^\d+\s+\d+', line):
            if current:
                merged.append(' '.join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        merged.append(' '.join(current))
    
    # Now each item in `merged` is a full player record with fields separated by spaces.
    # Re-join with tab separators for consistent parsing.
    cleaned_lines = []
    for rec in merged:
        # Split by whitespace (this may split names like "Stephon Castle" – we need to be careful)
        # Better: use regex to preserve names with spaces? But the data uses multiple spaces/tabs as separators.
        # We'll rely on the parser's ability to split by two or more spaces.
        # Here we simply output the line as is (with spaces) – the parser will handle it.
        cleaned_lines.append(rec)
    
    return '\n'.join(cleaned_lines)

# Read your raw file
with open('nba_raw.txt', 'r') as f:
    raw = f.read()

cleaned = clean_raw_table(raw)
print(cleaned)   # Copy this output and paste into NBA_TABLE
