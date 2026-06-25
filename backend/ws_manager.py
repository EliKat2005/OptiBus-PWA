"""
OptiBus WebSocket Manager — DevSecOps v4.0
Gestión de conexiones WebSocket con rate limiting por cliente,
heartbeat bidireccional, y broadcast eficiente.
"""

import asyncio
import json
import logging
import time
from collections import defaultdict

from config import WS_MAX_MESSAGES_PER_MINUTE, WS_TIMEOUT_SECONDS
from fastapi import WebSocket

logger = logging.getLogger("optibus-ws")


class RateLimitedConnection:
    """Wrapper para WebSocket con rate limiting individual."""

    def __init__(self, websocket: WebSocket, client_id: str):
        self.websocket = websocket
        self.client_id = client_id
        self.connected_at = time.time()
        self.last_message_at = time.time()
        self.message_timestamps: list[float] = []
        self.max_messages = WS_MAX_MESSAGES_PER_MINUTE
        self.window_seconds = 60

    def is_rate_limited(self) -> bool:
        """Verifica si esta conexión excedió su límite de mensajes."""
        now = time.time()
        # Limpiar timestamps viejos
        self.message_timestamps = [
            ts
            for ts in self.message_timestamps
            if now - ts < self.window_seconds
        ]
        if len(self.message_timestamps) >= self.max_messages:
            return True
        self.message_timestamps.append(now)
        self.last_message_at = now
        return False

    async def send_text(self, message: str) -> bool:
        """Envía texto con manejo de errores. Retorna True si exitoso."""
        try:
            await self.websocket.send_text(message)
            return True
        except Exception:
            return False

    async def close(self, code: int = 1000, reason: str = ""):
        """Cierra la conexión con manejo de errores."""
        try:
            await self.websocket.close(code=code, reason=reason)
        except Exception:
            pass


class ConnectionManager:
    """Manejador de conexiones WebSocket con rate limiting y heartbeat."""

    def __init__(self):
        self._connections: dict[str, RateLimitedConnection] = {}
        self._lock = asyncio.Lock()
        self._heartbeat_task: asyncio.Task | None = None
        self._started = False

    @property
    def active_count(self) -> int:
        """Número de conexiones activas."""
        return len(self._connections)

    async def start(self):
        """Inicia el heartbeat periódico."""
        if self._started:
            return
        self._started = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("WebSocket Connection Manager iniciado con heartbeat")

    async def stop(self):
        """Detiene el heartbeat y cierra todas las conexiones."""
        self._started = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        async with self._lock:
            for client_id, conn in list(self._connections.items()):
                await conn.close(1001, "Server shutting down")
            self._connections.clear()
        logger.info("WebSocket Connection Manager detenido")

    async def connect(self, websocket: WebSocket, client_id: str = "") -> str:
        """Acepta una nueva conexión WebSocket y le asigna un ID único."""
        await websocket.accept()
        if not client_id:
            client_id = f"client_{int(time.time() * 1000)}_{id(websocket)}"
        conn = RateLimitedConnection(websocket, client_id)
        async with self._lock:
            # Si ya existe una conexión con este client_id, cerrarla primero
            if client_id in self._connections:
                await self._connections[client_id].close(
                    4001, "New connection replacing old"
                )
            self._connections[client_id] = conn
        logger.info(
            f"WebSocket conectado: {client_id}. Conexiones activas: {self.active_count}"
        )
        return client_id

    async def disconnect(self, client_id: str):
        """Elimina una conexión del manager."""
        async with self._lock:
            if client_id in self._connections:
                del self._connections[client_id]
        logger.info(
            f"WebSocket desconectado: {client_id}. Conexiones activas: {self.active_count}"
        )

    async def is_rate_limited(self, client_id: str) -> bool:
        """Verifica si un cliente específico excedió su rate limit."""
        async with self._lock:
            conn = self._connections.get(client_id)
        if conn:
            return conn.is_rate_limited()
        return False

    async def send_to(self, client_id: str, message: str) -> bool:
        """Envía un mensaje a un cliente específico."""
        async with self._lock:
            conn = self._connections.get(client_id)
        if conn:
            return await conn.send_text(message)
        return False

    async def broadcast(self, message: str):
        """Envía un mensaje a TODAS las conexiones activas."""
        async with self._lock:
            connections = list(self._connections.items())

        disconnected = []
        for client_id, conn in connections:
            success = await conn.send_text(message)
            if not success:
                disconnected.append(client_id)

        # Limpiar conexiones muertas
        if disconnected:
            async with self._lock:
                for client_id in disconnected:
                    self._connections.pop(client_id, None)
            logger.debug(f"Limpiadas {len(disconnected)} conexiones muertas en broadcast")

    async def broadcast_to_authenticated(self, message: str, role: str = "admin"):
        """Broadcast solo a clientes autenticados con cierto rol (placeholder)."""
        # En el diseño actual, el WebSocket no mantiene estado de auth por conexión
        # Esto es un placeholder para futura implementación
        await self.broadcast(message)

    async def _heartbeat_loop(self):
        """Envía heartbeat periódico y limpia conexiones inactivas."""
        while self._started:
            await asyncio.sleep(30)
            now = time.time()
            timeout_clients = []

            async with self._lock:
                for client_id, conn in list(self._connections.items()):
                    # Si no hay actividad por más de 2x el timeout, desconectar
                    if now - conn.last_message_at > WS_TIMEOUT_SECONDS * 2:
                        timeout_clients.append(client_id)
                    else:
                        # Enviar heartbeat
                        try:
                            await conn.websocket.send_text(
                                json.dumps({"type": "heartbeat", "ts": now})
                            )
                        except Exception:
                            timeout_clients.append(client_id)

            for client_id in timeout_clients:
                logger.info(f"Desconectando cliente inactivo: {client_id}")
                async with self._lock:
                    conn = self._connections.pop(client_id, None)
                    if conn:
                        await conn.close(4002, "Heartbeat timeout")