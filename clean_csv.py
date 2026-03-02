import csv

input_file = 'nba_players.csv'   # your original CSV
output_file = 'nba_players_clean.csv'

with open(input_file, 'r', encoding='utf-8') as infile, \
     open(output_file, 'w', newline='', encoding='utf-8') as outfile:
    reader = csv.reader(infile)
    writer = csv.writer(outfile, quoting=csv.QUOTE_MINIMAL)
    for row in reader:
        # The injury column is at index 6 (0-based). If it contains commas, it will already be quoted by csv.reader.
        # We just write it as is; csv.writer will quote if necessary.
        writer.writerow(row)

print("Cleaned CSV written to nba_players_clean.csv")
