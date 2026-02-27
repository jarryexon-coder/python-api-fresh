# In railway_update_nba.py, replace the download function:

def download_from_basketballmonster():
    """Download and parse NBA data from Basketball Monster."""
    url = "https://basketballmonster.com/playerrankings.aspx"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Parse with pandas (handles HTML tables well)
        import pandas as pd
        tables = pd.read_html(io.StringIO(response.text))
        
        # The rankings table is usually the first or second table
        df = tables[0]  # Try first table
        if 'Name' not in df.columns and len(tables) > 1:
            df = tables[1]  # Try second table
        
        # Clean up column names
        df.columns = [col.strip() for col in df.columns]
        
        # Save to CSV
        csv_path = '/tmp/nba_stats.csv'
        df.to_csv(csv_path, index=False)
        
        print(f"✅ Downloaded {len(df)} players")
        return csv_path
        
    except Exception as e:
        print(f"❌ Download failed: {e}")
        return None
