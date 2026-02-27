import requests
import time

url = "https://python-api-fresh-production.up.railway.app/api/admin/update-nba-manual"
headers = {
    "X-API-Key": "test123",
    "Content-Type": "application/json"
}

print(f"Testing {url}")
print("Waiting for deployment to complete...")
time.sleep(5)  # Give Railway a moment

try:
    response = requests.post(url, headers=headers, json={})
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
except Exception as e:
    print(f"Error: {e}")
