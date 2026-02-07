import re
from datetime import datetime, timedelta
import time
from collections import defaultdict

with open('app.py', 'r') as f:
    content = f.read()

print("🛡️ Adding rate limiting to app.py...")

# Add imports at the top if not present
imports_to_add = []
if 'from datetime import datetime' in content and 'timedelta' not in content:
    content = content.replace('from datetime import datetime', 'from datetime import datetime, timedelta')
    print("✅ Added timedelta import")

if 'from collections import defaultdict' not in content:
    # Find where imports end
    import_section_end = content.find('\n\n')
    if import_section_end == -1:
        import_section_end = content.find('\n@app')
    
    if import_section_end != -1:
        content = content[:import_section_end] + '\nfrom collections import defaultdict' + content[import_section_end:]
        print("✅ Added defaultdict import")

# Add rate limiting storage and functions
rate_limit_code = '''

# Rate limiting storage
request_log = defaultdict(list)

def is_rate_limited(ip, endpoint, limit=30, window=60):
    """Check if IP is rate limited for an endpoint"""
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=window)
    
    # Clean old requests
    request_log[ip] = [t for t in request_log[ip] if t > window_start]
    
    if len(request_log[ip]) >= limit:
        return True
    
    request_log[ip].append(now)
    return False

# Rate limiting middleware
@app.before_request
def check_rate_limit():
    """Apply rate limiting to all endpoints"""
    # Skip health checks
    if flask_request.path == '/api/health':
        return None
    
    ip = flask_request.remote_addr or 'unknown'
    endpoint = flask_request.path
    
    # Different limits for different endpoints
    if '/api/parlay/suggestions' in endpoint:
        if is_rate_limited(ip, endpoint, limit=5, window=60):
            return jsonify({
                'success': False,
                'error': 'Rate limit exceeded for parlay suggestions. Please wait 1 minute.',
                'retry_after': 60
            }), 429
    
    elif '/api/prizepicks/selections' in endpoint:
        if is_rate_limited(ip, endpoint, limit=10, window=60):
            return jsonify({
                'success': False,
                'error': 'Rate limit exceeded for prize picks. Please wait 1 minute.',
                'retry_after': 60
            }), 429
    
    # General rate limit for all other endpoints
    elif is_rate_limited(ip, endpoint, limit=30, window=60):
        return jsonify({
            'success': False,
            'error': 'Rate limit exceeded. Please wait 1 minute.',
            'retry_after': 60
        }), 429
    
    return None

# Request logging middleware
@app.before_request
def log_request():
    if flask_request.path != '/api/health':
        print(f"📥 {datetime.utcnow().strftime('%H:%M:%S')} - {flask_request.method} {flask_request.path}")

'''

# Insert rate limiting code before the first endpoint
first_route_pos = content.find('@app.route')
if first_route_pos != -1:
    content = content[:first_route_pos] + rate_limit_code + content[first_route_pos:]
    print("✅ Added rate limiting middleware")

# Update health endpoint to show rate limits
health_rate_info = '''        "rate_limits": {
            "general": "30 requests/minute",
            "prizepicks_selections": "10 requests/minute",
            "parlay_suggestions": "5 requests/minute"
        },'''

# Add rate limits to health response
if '"message":' in content:
    # Find a good place to insert rate limits in health response
    message_pos = content.find('"message":')
    if message_pos != -1:
        # Find the next comma after message
        comma_pos = content.find(',', message_pos)
        if comma_pos != -1:
            content = content[:comma_pos+1] + '\n        ' + health_rate_info + content[comma_pos+1:]
            print("✅ Added rate limit info to health endpoint")

with open('app.py', 'w') as f:
    f.write(content)

print("🛡️ Rate limiting added successfully!")
print("   • General: 30 requests/minute")
print("   • PrizePicks: 10 requests/minute")
print("   • Parlay: 5 requests/minute")
