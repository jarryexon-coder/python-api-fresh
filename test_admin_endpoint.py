#!/usr/bin/env python3
"""
Test the admin NBA update endpoint.
"""

import requests
import sys
import os

# Configuration
RAILWAY_URL = "https://python-api-fresh-production.up.railway.app"
# Use your actual admin key from Railway
ADMIN_KEY = "test123"  # Change this to your actual key

def test_update():
    """Test the update endpoint."""
    url = f"{RAILWAY_URL}/api/admin/update-nba-manual"
    
    headers = {
        "X-API-Key": ADMIN_KEY,
        "Content-Type": "application/json"
    }
    
    print(f"🔑 Using API Key: {ADMIN_KEY}")
    print(f"📡 Testing URL: {url}")
    
    try:
        response = requests.post(url, headers=headers, json={}, timeout=10)
        
        print(f"📊 Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print("✅ Success!")
            print(f"   Message: {data.get('message')}")
            print(f"   Players: {data.get('player_count')}")
            print(f"   Time: {data.get('timestamp')}")
        else:
            print(f"❌ Failed: {response.text}")
            
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to Railway")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_update()
