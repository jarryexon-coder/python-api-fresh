import json
import os
import base64
import requests
import datetime
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

ACCESS_KEY = "23a24ba7-5a2a-4f8f-a733-ca288540bae5"  # Your key ID
BASE_URL = "https://api.elections.kalshi.com"
PATH = "/trade-api/v2/markets"
PARAMS = {"status": "open", "limit": 10}

def load_private_key_from_file(file_path):
    with open(file_path, "rb") as key_file:
        return serialization.load_pem_private_key(
            key_file.read(),
            password=None,
            backend=default_backend()
        )

def sign_pss_text(private_key, text):
    message = text.encode('utf-8')
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')

def get_kalshi_headers(method, path):
    timestamp_ms = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
    timestamp_str = str(timestamp_ms)
    path_without_query = path.split('?')[0]
    private_key = load_private_key_from_file("kalshi-key.pem")
    msg = timestamp_str + method.upper() + path_without_query
    sig = sign_pss_text(private_key, msg)
    return {
        'KALSHI-ACCESS-KEY': ACCESS_KEY,
        'KALSHI-ACCESS-SIGNATURE': sig,
        'KALSHI-ACCESS-TIMESTAMP': timestamp_str,
    }

headers = get_kalshi_headers('GET', PATH)
print("Headers:")
for k, v in headers.items():
    print(f"  {k}: {v}")

resp = requests.get(f"{BASE_URL}{PATH}", headers=headers, params=PARAMS)
data = resp.json()
if data.get('markets'):
    print(json.dumps(data['markets'][0], indent=2))
