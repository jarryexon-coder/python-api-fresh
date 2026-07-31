"""
Injury Data and Types
"""

INJURY_TYPES = {
    "ankle": {"typical_timeline": "1-2 weeks", "severity": "moderate"},
    "knee": {"typical_timeline": "2-4 weeks", "severity": "moderate"},
    "acl": {"typical_timeline": "6-9 months", "severity": "severe"},
    "hamstring": {"typical_timeline": "2-3 weeks", "severity": "moderate"},
    "groin": {"typical_timeline": "1-2 weeks", "severity": "moderate"},
    "calf": {"typical_timeline": "1-2 weeks", "severity": "mild"},
    "quad": {"typical_timeline": "1-2 weeks", "severity": "mild"},
    "back": {"typical_timeline": "1-3 weeks", "severity": "moderate"},
    "shoulder": {"typical_timeline": "2-4 weeks", "severity": "moderate"},
    "wrist": {"typical_timeline": "2-4 weeks", "severity": "moderate"},
    "foot": {"typical_timeline": "2-4 weeks", "severity": "moderate"},
    "concussion": {"typical_timeline": "1-2 weeks", "severity": "moderate"},
    "illness": {"typical_timeline": "3-7 days", "severity": "mild"},
    "covid": {"typical_timeline": "5-10 days", "severity": "moderate"},
    "personal": {"typical_timeline": "unknown", "severity": "unknown"},
    "rest": {"typical_timeline": "1 game", "severity": "maintenance"},
}

def get_fallback_nba_injuries():
    """Return fallback NBA injury data."""
    return [
        {"player": "Jalen Johnson", "team": "ATL", "status": "Out", "injury": "Shoulder injury - season ending", "expected_return": "season"},
        {"player": "Larry Nance Jr.", "team": "ATL", "status": "Out", "injury": "Knee surgery", "expected_return": "2-3 weeks"},
        {"player": "Kristaps Porzingis", "team": "BOS", "status": "Day-to-day", "injury": "Illness", "expected_return": "day-to-day"},
        {"player": "Cam Thomas", "team": "BKN", "status": "Out", "injury": "Hamstring strain", "expected_return": "2-3 weeks"},
        {"player": "LaMelo Ball", "team": "CHA", "status": "Out", "injury": "Ankle injury", "expected_return": "2-3 weeks"},
        {"player": "Lonzo Ball", "team": "CHI", "status": "Out", "injury": "Knee recovery", "expected_return": "season"},
        {"player": "Evan Mobley", "team": "CLE", "status": "Day-to-day", "injury": "Ankle sprain", "expected_return": "day-to-day"},
        {"player": "Kyrie Irving", "team": "DAL", "status": "Out", "injury": "Knee surgery", "expected_return": "season"},
        {"player": "Jamal Murray", "team": "DEN", "status": "Day-to-day", "injury": "Knee inflammation", "expected_return": "day-to-day"},
        {"player": "Jaden Ivey", "team": "DET", "status": "Out", "injury": "Leg fracture", "expected_return": "season"},
        {"player": "Draymond Green", "team": "GSW", "status": "Day-to-day", "injury": "Calf tightness", "expected_return": "day-to-day"},
        {"player": "Jabari Smith Jr.", "team": "HOU", "status": "Out", "injury": "Hand fracture", "expected_return": "3-4 weeks"},
        {"player": "Myles Turner", "team": "IND", "status": "Day-to-day", "injury": "Ankle", "expected_return": "day-to-day"},
        {"player": "Kawhi Leonard", "team": "LAC", "status": "Day-to-day", "injury": "Knee management", "expected_return": "day-to-day"},
        {"player": "LeBron James", "team": "LAL", "status": "Day-to-day", "injury": "Ankle soreness", "expected_return": "day-to-day"},
        {"player": "Ja Morant", "team": "MEM", "status": "Out", "injury": "Shoulder injury", "expected_return": "2-3 weeks"},
        {"player": "Jimmy Butler", "team": "MIA", "status": "Day-to-day", "injury": "Ankle sprain", "expected_return": "day-to-day"},
        {"player": "Giannis Antetokounmpo", "team": "MIL", "status": "Day-to-day", "injury": "Knee soreness", "expected_return": "day-to-day"},
        {"player": "Mike Conley", "team": "MIN", "status": "Questionable", "injury": "Hamstring", "expected_return": "game-time decision"},
        {"player": "Zion Williamson", "team": "NOP", "status": "Day-to-day", "injury": "Hamstring tightness", "expected_return": "day-to-day"},
        {"player": "Josh Hart", "team": "NYK", "status": "Probable", "injury": "Knee soreness", "expected_return": "expected to play"},
        {"player": "Chet Holmgren", "team": "OKC", "status": "Out", "injury": "Hip fracture", "expected_return": "season"},
        {"player": "Franz Wagner", "team": "ORL", "status": "Out", "injury": "Ankle injury", "expected_return": "2-3 weeks"},
        {"player": "Joel Embiid", "team": "PHI", "status": "Out", "injury": "Knee injury management", "expected_return": "TBD"},
        {"player": "Victor Wembanyama", "team": "SAS", "status": "Out", "injury": "Shoulder surgery", "expected_return": "season"},
        {"player": "Brandon Ingram", "team": "TOR", "status": "Out", "injury": "Ankle sprain", "expected_return": "2-3 weeks"},
        {"player": "Jordan Clarkson", "team": "UTA", "status": "Questionable", "injury": "Foot", "expected_return": "game-time decision"},
        {"player": "Bilal Coulibaly", "team": "WAS", "status": "Out", "injury": "Wrist injury", "expected_return": "2-3 weeks"},
    ]

def get_fallback_nfl_injuries():
    """Return fallback NFL injury data."""
    return [
        {"player": "Patrick Mahomes", "team": "KC", "status": "Day-to-day", "injury": "Ankle sprain", "expected_return": "day-to-day"},
        {"player": "Joe Burrow", "team": "CIN", "status": "Probable", "injury": "Calf strain", "expected_return": "expected to play"},
        {"player": "Christian McCaffrey", "team": "SF", "status": "Out", "injury": "Knee injury", "expected_return": "2-3 weeks"},
    ]
