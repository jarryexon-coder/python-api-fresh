import os
import sys
from flask import Flask, jsonify
from flask_cors import CORS

# Write to stderr for Railway logs (important!)
print("🚀 Python API Starting on Railway...", file=sys.stderr)
print(f"Python: {sys.version}", file=sys.stderr)
print(f"Port: {os.environ.get('PORT', '8000')}", file=sys.stderr)
print(f"CWD: {os.getcwd()}", file=sys.stderr)
sys.stderr.flush()

app = Flask(__name__)

# Enable CORS
CORS(app)

@app.route('/')
def home():
    print("📞 Home endpoint called", file=sys.stderr)
    return jsonify({
        "status": "online",
        "service": "Python Fantasy API",
        "version": "1.0.0",
        "timestamp": "2024-02-09T05:10:00Z",
        "environment": "railway"
    })

@app.route('/api/health')
def health():
    return jsonify({
        "status": "healthy",
        "message": "API is running",
        "timestamp": "2024-02-09T05:10:00Z"
    })

@app.route('/api/fantasy/players')
def get_players():
    print("📊 Fantasy players endpoint called", file=sys.stderr)
    return jsonify({
        "success": True,
        "players": [
            {"id": 1, "name": "LeBron James", "team": "Lakers"},
            {"id": 2, "name": "Stephen Curry", "team": "Warriors"}
        ]
    })

# DO NOT add if __name__ == '__main__' block
# Railway uses gunicorn directly
