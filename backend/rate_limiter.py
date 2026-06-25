"""
OptiBus Distributed Rate Limiter — DevSecOps v4.0
Rate limiting con Redis con fallback a memoria. Validación de X-Forwarded-For.
"""

import asyncio
import logging
import time
from collections import defaultdict

import redis.asyncio as aioredis
from config import REDIS_URL, RL_MAX_REQUESTS, RL_WINDOW_SECONDS, is_trusted_proxy

logger = logging.getLogger("optibus-rate-limiter")

# ── Redis connection ──
_redis_client: aioredis.Redis | None = None
_redis_last_attempt: float = 0.0
_REDIS_RETRY_INTERVAL = 30


async def get_redis() -> aioredis.Redis | None:
    """Obtiene cliente Redis con reintento periódico cada 30s si falló antes."""
    global _redis_client, _redis_last_attempt
    now = time.time()
    if _redis_client is not None:
        try:
            await _redis_client.ping()
            return _redis_client
        except Exception:
            logger.warning("Redis desconectado. Reintentando conexión...")
            _redis_client = None
    if now - _redis_last_attempt >= _REDIS_RETRY_INTERVAL:
        _redis_last_attempt = now
        try:
            _redis_client = aioredis.from_url(
                REDIS_URL, encoding="utf-8", decode_responses=True
            )
            await _redis_client.ping()
            logger.info("Conectado a Redis para rate limiting distribuido")
            return _redis_client
        except Exception as e:
            logger.warning(
                f"Redis no disponible ({type(e).__name__}), usando rate limiter en memoria. "
                f"Reintento en {_REDIS_RETRY_INTERVAL}s"
            )
            _redis_client = None
    return None


class DistributedRateLimiter:
    """Rate limiter con fallback a memoria si Redis no está disponible."""

    def __init__(
        self,
        max_requests: int = RL_MAX_REQUESTS,
        window_seconds: int = RL_WINDOW_SECONDS,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.fallback_clients: dict[str, list[float]] = defaultdict(list)

    async def is_allowed(self, client_ip: str) -> bool:
        """Verifica si el cliente está dentro del rate limit."""
        r = await get_redis()
        if r:
            key = f"rl:{client_ip}"
            try:
                current = await r.incr(key)
                if current == 1:
                    await r.expire(key, self.window_seconds)
                return current <= self.max_requests
            except Exception as e:
                logger.debug(f"Redis rate limit fallback: {e}")

        # Fallback en memoria
        now = time.time()
        self.fallback_clients[client_ip] = [
            ts
            for ts in self.fallback_clients[client_ip]
            if now - ts < self.window_seconds
        ]
        if len(self.fallback_clients[client_ip]) >= self.max_requests:
            return False
        self.fallback_clients[client_ip].append(now)
        return True


def get_real_ip(client_ip: str, x_forwarded_for: str) -> str:
    """
    DevSecOps: Obtiene la IP real del cliente.
    SOLO confía en X-Forwarded-For si viene de un proxy confiable (Caddy en red interna).
    """
    if x_forwarded_for:
        # X-Forwarded-For: client, proxy1, proxy2...
        ips = [ip.strip() for ip in x_forwarded_for.split(",")]
        # El último IP confiable es nuestro proxy (Caddy), el primero es el cliente real
        if len(ips) >= 1:
            # Verificar que el último IP en la cadena es un proxy confiable (Caddy)
            last_proxy = ips[-1] if len(ips) > 1 else client_ip
            if is_trusted_proxy(last_proxy) or is_trusted_proxy(client_ip):
                # El cliente real es el primer IP en X-Forwarded-For
                real_ip = ips[0]
                if real_ip:
                    return real_ip

    # Si no hay proxy confiable, usar la IP directa del socket
    return client_ip or "unknown"