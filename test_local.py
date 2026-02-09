# test_local.py
from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({'message': 'Test app running'})

@app.route('/api/test')
def test():
    return jsonify({'success': True, 'test': 'local'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3002))
    print(f"Starting test server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)
