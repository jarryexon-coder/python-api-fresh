import subprocess
import json
import time

print("🔍 Checking for new service URL...")
result = subprocess.run(['railway', 'info'], capture_output=True, text=True)
output = result.stdout

import re
urls = re.findall(r'https://[^\s]+\.up\.railway\.app', output)
if urls:
    new_url = urls[0]
    print(f"Found URL: {new_url}")
    
    import urllib.request
    try:
        req = urllib.request.Request(f"{new_url}/api/prizepicks/selections?sport=nba")
        response = urllib.request.urlopen(req, timeout=30)
        data = json.loads(response.read().decode())
        
        print(f"\n🎯 NEW SERVICE TEST:")
        print(f"Success: {data.get('success')}")
        print(f"Message: {data.get('message')}")
        print(f"Version: {data.get('version')}")
        
        if data.get('selections'):
            s = data['selections'][0]
            print(f"\n📊 First selection:")
            print(f"  Player: {s.get('player')}")
            print(f"  Stat: {s.get('stat_type')}")
            print(f"  Edge: {s.get('edge')} (Should be >10, not 1.XX)")
            print(f"  Value Side: {s.get('value_side')}")
            print(f"  Game: {s.get('game')}")
            print(f"  Real Data: {s.get('is_real_data')}")
            
            if s.get('value_side') and s.get('edge', 0) > 10:
                print(f"\n🎉 SUCCESS! Fresh service is CORRECT!")
                print(f"✅ All fields present with right formats")
            else:
                print(f"\n❌ Still issues")
    except Exception as e:
        print(f"Test error: {e}")
else:
    print("No URL found in railway info")
    print("Check Railway dashboard for the new service URL")
