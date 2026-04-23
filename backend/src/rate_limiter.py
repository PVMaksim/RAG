"""
rate_limiter.py — rate limiting для FastAPI бэкенда.

Лимиты:
  - /api/search/*   : 30 запросов/мин  (SSE стриминг дорогой)
  - /api/projects/* : 20 запросов/мин  (сканирование тяжёлое)
  - /health         : без лимита
  - остальное       : 60 запросов/мин

В production можно заменить backend на Redis:
  from slowapi.backends.redis import RedisBackend
  limiter = Limiter(key_func=get_remote_address, storage_uri="redis://redis:6379")
"""
import logging

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

log = logging.getLogger(__name__)

# Singleton — импортируется в main.py и роутерах
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60/minute"],
    headers_enabled=True,   # X-RateLimit-* заголовки в ответе
)
