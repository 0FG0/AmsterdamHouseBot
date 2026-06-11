import asyncio
import logging
from collections.abc import Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_HTTPX_CLIENTS: dict[tuple[str, int], httpx.AsyncClient] = {}
_SHARED_SESSIONS: dict[tuple[str, int], Any] = {}
_LOCKS: dict[tuple[str, int], asyncio.Lock] = {}


def _key(name: str) -> tuple[str, int]:
    return (name, id(asyncio.get_running_loop()))


def _lock_for(key: tuple[str, int]) -> asyncio.Lock:
    lock = _LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[key] = lock
    return lock


async def get_httpx_client(
    name: str,
    *,
    timeout: float = 30,
    follow_redirects: bool = True,
) -> httpx.AsyncClient:
    key = _key(f"httpx:{name}")
    client = _HTTPX_CLIENTS.get(key)
    if client and not client.is_closed:
        return client

    async with _lock_for(key):
        client = _HTTPX_CLIENTS.get(key)
        if client and not client.is_closed:
            return client

        client = httpx.AsyncClient(timeout=timeout, follow_redirects=follow_redirects)
        _HTTPX_CLIENTS[key] = client
        return client


async def get_shared_session(name: str, factory: Callable[[], Any]) -> Any:
    key = _key(f"session:{name}")
    session = _SHARED_SESSIONS.get(key)
    if session is not None:
        return session

    async with _lock_for(key):
        session = _SHARED_SESSIONS.get(key)
        if session is not None:
            return session

        session = factory()
        _SHARED_SESSIONS[key] = session
        return session


async def close_httpx_client(name: str) -> None:
    key = _key(f"httpx:{name}")
    async with _lock_for(key):
        client = _HTTPX_CLIENTS.pop(key, None)
    await _close_resource(client, "HTTP client")


async def close_shared_session(name: str) -> None:
    key = _key(f"session:{name}")
    async with _lock_for(key):
        session = _SHARED_SESSIONS.pop(key, None)
    await _close_resource(session, "HTTP session")


async def close_shared_clients() -> None:
    clients = list(_HTTPX_CLIENTS.values())
    sessions = list(_SHARED_SESSIONS.values())
    _HTTPX_CLIENTS.clear()
    _SHARED_SESSIONS.clear()
    _LOCKS.clear()

    for client in clients:
        await _close_resource(client, "HTTP client")

    for session in sessions:
        await _close_resource(session, "HTTP session")


async def _close_resource(resource: Any, label: str) -> None:
    if resource is None:
        return

    close = getattr(resource, "aclose", None) or getattr(resource, "close", None)
    if close is None:
        return

    try:
        result = close()
        if asyncio.iscoroutine(result):
            await result
    except Exception as exc:
        logger.warning("Failed to close shared %s: %s", label, exc)
