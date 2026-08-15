# -*- coding: utf-8 -*-
"""Connection configuration: env vars with port auto-discovery.

pyRevit Routes serves the first Revit instance on 48884, the second on 48885,
and so on. REVIT_PORT pins a port explicitly; otherwise we probe the default
range and cache the first port that answers on the /revit_mcp/ path (so a
stranger service squatting the port number is not mistaken for Revit).

Two probe paths:
- async (resolve_port_async/base_url_async): the hot path used by tool calls.
  Probes all ports concurrently on the shared client, and caches an all-dead
  result for NEGATIVE_CACHE_TTL so tool calls with Revit closed fail fast
  instead of re-probing (and blocking) on every call.
- sync (resolve_port/base_url): used from sync contexts (doctor, tests).
"""
import asyncio
import os
import time

import httpx

from .http_client import get_client

DEFAULT_PORTS = (48884, 48885, 48886, 48887)
PROBE_TIMEOUT = 1.5
NEGATIVE_CACHE_TTL = 8.0  # seconds; Revit startup takes minutes, 8s is safe

_cached_port = None
_probe_failed_at = 0.0  # monotonic timestamp of the last all-ports-dead probe


def get_host():
    return os.environ.get("REVIT_HOST", "127.0.0.1")


def http_port():
    """Port for the MCP server's own HTTP transports (--sse/--http/--combined)."""
    return int(os.environ.get("REVIT_MCP_HTTP_PORT", "8000"))


def invalidate_port_cache():
    """Forget the discovered port after a connection failure.

    Deliberately does NOT clear the negative cache: the caller's retry should
    fail fast when Revit is down, not pay a second full probe round.
    """
    global _cached_port
    _cached_port = None


def _status_url(port):
    return "http://{}:{}/revit_mcp/status/".format(get_host(), port)


def _is_ours(status_code):
    # 200 = healthy; 503 = routes up but no document open - still ours.
    # 404 means something else owns the port.
    return status_code in (200, 503)


async def _probe_async(port):
    try:
        r = await get_client().get(_status_url(port), timeout=PROBE_TIMEOUT)
        return _is_ours(r.status_code)
    except httpx.HTTPError:
        return False


async def resolve_port_async():
    global _cached_port, _probe_failed_at
    env_port = os.environ.get("REVIT_PORT")
    if env_port:
        return int(env_port)
    if _cached_port is not None:
        return _cached_port
    if time.monotonic() - _probe_failed_at < NEGATIVE_CACHE_TTL:
        return DEFAULT_PORTS[0]  # fail fast; the caller gets ConnectError
    results = await asyncio.gather(*(_probe_async(p) for p in DEFAULT_PORTS))
    for port, alive in zip(DEFAULT_PORTS, results):
        if alive:
            _cached_port = port
            return port
    _probe_failed_at = time.monotonic()
    return DEFAULT_PORTS[0]


async def base_url_async():
    return "http://{}:{}/revit_mcp".format(get_host(), await resolve_port_async())


def _probe(port):
    """Sync probe for sync contexts (doctor). verify=False: loopback http."""
    try:
        r = httpx.get(_status_url(port), timeout=PROBE_TIMEOUT, verify=False)
        return _is_ours(r.status_code)
    except httpx.HTTPError:
        return False


def resolve_port():
    global _cached_port
    env_port = os.environ.get("REVIT_PORT")
    if env_port:
        return int(env_port)
    if _cached_port is not None:
        return _cached_port
    for port in DEFAULT_PORTS:
        if _probe(port):
            _cached_port = port
            return port
    return DEFAULT_PORTS[0]


def base_url():
    return "http://{}:{}/revit_mcp".format(get_host(), resolve_port())
