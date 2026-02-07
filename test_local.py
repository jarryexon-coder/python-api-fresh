# test_local.py
import requests
import time

print("Testing locally...")
try:
    response = requests.get("http://localhost:8000/api/health", timeout=5)
    print(f"✅ Local health check: {response.status_code}")
    if response.status_code == 200:
        print(f"Response: {response.json()}")
except Exception as e:
    print(f"❌ Local test failed: {e}")
