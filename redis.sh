import redis
r = redis.Redis(host='your-redis-host', port=6379, password='your-password')
key = "user:gen:DRlS9wfiFnbNnC0rGgsGcrzEjuY2"
r.delete(key)  # Delete corrupted entry
print(f"Deleted {key}")
