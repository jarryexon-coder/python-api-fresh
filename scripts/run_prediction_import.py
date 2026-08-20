#!/usr/bin/env python3
"""One-shot Railway Cron runner for settled prediction imports."""
from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


secret = os.getenv("PREDICTION_IMPORT_SECRET", "")
url = os.getenv(
    "PREDICTION_IMPORT_URL",
    "https://pleasing-determination-production.up.railway.app/api/prediction-ledger/import-results",
)

if not secret:
    print("PREDICTION_IMPORT_SECRET is not configured", file=sys.stderr)
    raise SystemExit(2)

request = Request(url, method="POST", headers={"X-Prediction-Import-Key": secret, "Accept": "application/json"})
try:
    with urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))
        print(json.dumps(payload, sort_keys=True))
        raise SystemExit(0 if payload.get("success") else 1)
except HTTPError as error:
    print(f"Importer failed with HTTP {error.code}: {error.read().decode('utf-8', 'replace')}", file=sys.stderr)
    raise SystemExit(1)
except URLError as error:
    print(f"Importer request failed: {error.reason}", file=sys.stderr)
    raise SystemExit(1)
