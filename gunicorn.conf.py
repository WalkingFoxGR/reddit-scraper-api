# gunicorn.conf.py
import os

# Server socket
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
backlog = 2048

# Worker processes
workers = 2
worker_class = "sync"
worker_connections = 1000

# Timeout settings - Extended for Reddit API calls
timeout = 600  # 10 minutes (important for slow Reddit responses)
keepalive = 600
graceful_timeout = 30

# Worker lifecycle
max_requests = 1000
max_requests_jitter = 100

# Logging
loglevel = "info"
accesslog = "-"
errorlog = "-"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Performance
preload_app = True
