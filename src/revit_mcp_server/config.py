# -*- coding: utf-8 -*-
"""Connection configuration: env vars with port auto-discovery.

pyRevit Routes serves the first Revit instance on 48884, the second on 48885,
and so on. REVIT_PORT pins a port explicitly; otherwise we probe the default
range and cache the first port that answers on the /revit_mcp/ path (so a
stranger service squatting the port number is not mistaken for Revit).
"""
import os

import httpx

DEFAULT_PORTS = (48884, 48885, 48886, 48887)
PROBE_TIMEOUT = 1.5

_cached_port = None


def get_host():
    return os.environ.get("REVIT_HOST", "127.0.0.1")


def http_port():
    """Port for the MCP server's own HTTP transports (--sse/--http/--combined)."""
    return int(os.environ.get("REVIT_MCP_HTTP_PORT", "8000"))


def invalidate_port_cache():
    global _cached_port
    _cached_port = None


def _probe(port):
    """True if pyRevit Routes with our API is alive on this port.

    200 = healthy; 503 = routes up but no document open — still ours.
    404 means something else owns the port.
    """
    try:
        r = httpx.get(
            "http://{}:{}/revit_mcp/status/".format(get_host(), port),
            timeout=PROBE_TIMEOUT,
        )
        return r.status_code in (200, 503)
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
    # Nothing alive: report the conventional default so error messages point at
    # the right place. Deliberately not cached — the next call re-probes.
    return DEFAULT_PORTS[0]


def base_url():
    return "http://{}:{}/revit_mcp".format(get_host(), resolve_port())
