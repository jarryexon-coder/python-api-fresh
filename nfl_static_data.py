from json import load
from pathlib import Path

with (Path(__file__).resolve().parent / "nfl_players_data.json").open(
    encoding="utf-8"
) as source:
    NFL_PLAYERS = load(source)
