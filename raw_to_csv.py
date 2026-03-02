import csv
import re

def parse_raw_to_csv(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Find the header line (contains the column names)
    header_idx = None
    for i, line in enumerate(lines):
        if 'Round' in line and 'Name' in line and 'Team' in line:
            header_idx = i
            break
    if header_idx is None:
        print("Header not found.")
        return

    # Extract header and clean it (remove trailing $, split by whitespace)
    header_line = lines[header_idx].strip()
    # Remove any trailing $ and split on one or more spaces/tabs
    header_line = re.sub(r'\$', '', header_line)
    headers = re.split(r'\s+', header_line)
    # Remove empty strings if any
    headers = [h for h in headers if h]

    # Now process data lines
    data_lines = lines[header_idx+1:]
    cleaned_rows = []

    for line in data_lines:
        line = line.strip()
        if not line:
            continue
        # Remove any trailing $ and split on whitespace
        line = re.sub(r'\$', '', line)
        fields = re.split(r'\s+', line)

        # If the number of fields doesn't match headers, try to fix:
        # sometimes the injury column is empty, causing missing fields.
        # We'll pad with empty strings if too few.
        if len(fields) < len(headers):
            # Insert empty string for missing injury or other fields
            # Heuristic: if fields length is headers-1, maybe injury missing.
            # But we'll just pad at the end.
            fields += [''] * (len(headers) - len(fields))
        elif len(fields) > len(headers):
            # Too many fields – maybe a player name with spaces was split.
            # Merge extra fields into the name column.
            # Name is at index 3. Merge all fields from index 3 to (len(headers)-?)...
            # This is complex; a simpler approach: use the original parsing that failed
            # but now we have a chance to fix by using the fact that the data is tab-separated originally.
            # Since we're here, we'll assume the data is messy and skip this line for manual inspection.
            print(f"Warning: line has {len(fields)} fields, expected {len(headers)}. Skipping.")
            continue

        cleaned_rows.append(fields)

    # Write to CSV
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(cleaned_rows)

    print(f"Converted {len(cleaned_rows)} rows to {output_file}")

if __name__ == '__main__':
    parse_raw_to_csv('nba_raw.txt', 'nba_players_clean.csv')
