import os
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# Copy the exact value from Railway (including newlines) into a triple‑quoted string
key_str = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA1toymJdOAQxT8VVtlVZBh
eA6e+TL8fW5gkfXEBaqH82AMtHc
...
-----END RSA PRIVATE KEY-----"""

try:
    private_key = serialization.load_pem_private_key(
        key_str.encode('utf-8'),
        password=None,
        backend=default_backend()
    )
    print("✅ Key loaded successfully")
except Exception as e:
    print(f"❌ Failed: {e}")
