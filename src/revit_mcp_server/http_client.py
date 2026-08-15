# -*- coding: utf-8 -*-
"""Process-wide shared HTTP client.

Constructing httpx.AsyncClient per request costs ~750ms: with the default
verify=True, httpx eagerly builds an SSL context, which loads the 283KB
certifi CA bundle from disk — per client instance, uncached. All transport
here is plain http:// to 127.0.0.1 (pyRevit Routes has no TLS), so
certificate verification can never apply; verify=False skips even the
one-time cost.

If REVIT_HOST is ever pointed at a remote https endpoint, this must be
revisited — verify=False would silently disable certificate checking there.
"""
import asyncio

import httpx

_client = None
_client_loop = None


def get_client() -> httpx.AsyncClient:
    """Shared client, lazily bound to the running event loop.

    Re-created if the loop changed (pytest spins up a fresh loop per test
    session; a client bound to a closed loop raises RuntimeError on use).
    """
    global _client, _client_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _client is None or (_client_loop is not None and _client_loop is not loop):
        _client = httpx.AsyncClient(
            verify=False,
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_keepalive_connections=4),
        )
        _client_loop = loop
    return _client


def reset_client():
    """Drop the shared client (test hook; next get_client() rebuilds)."""
    global _client, _client_loop
    _client = None
    _client_loop = None
