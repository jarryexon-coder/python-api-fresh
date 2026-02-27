# fetch_nba_basketballmonster.py
import requests
import pandas as pd
import io
import os
import tempfile
from datetime import datetime

def fetch_basketballmonster_data():
    """Fetch and parse NBA data from Basketball Monster."""
    url = "https://basketballmonster.com/playerrankings.aspx"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        print(f"📥 Fetching data from {url}")
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Use pandas to read HTML tables
        tables = pd.read_html(io.StringIO(response.text))
        
        # Find the correct table (usually the first or second large table)
        df = None
        for table in tables:
            if 'Name' in table.columns and 'Team' in table.columns:
                df = table
                break
        
        if df is None:
            # Try first table as fallback
            df = tables[0]
        
        # Clean up column names
        df.columns = [col.strip() for col in df.columns]
        
        # Save to temporary CSV
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, dir='/tmp')
        df.to_csv(temp_file.name, index=False)
        
        print(f"✅ Saved {len(df)} players to {temp_file.name}")
        return temp_file.name
        
    except Exception as e:
        print(f"❌ Error fetching data: {e}")
        return None

if __name__ == "__main__":
    fetch_basketballmonster_data()
