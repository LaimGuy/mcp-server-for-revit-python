# -*- coding: utf-8 -*-
"""Async port resolution: pinning, positive cache, negative cache with TTL."""
import httpx
import pytest

from revit_mcp_server import config, http_client


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.delenv("REVIT_PORT", raising=False)
    config._cached_port = None
    config._probe_failed_at = 0.0
    yield
    config._cached_port = None
    config._probe_failed_at = 0.0


def _install_transport(monkeypatch, handler, counter):
    real_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        def counting_handler(request):
            counter.append(request.url.port)
            return handler(request)

        kwargs["transport"] = httpx.MockTransport(counting_handler)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
    http_client.reset_client()


async def test_env_pin_short_circuits(monkeypatch):
    attempts = []
    _install_transport(monkeypatch, lambda r: httpx.Response(200), attempts)
    monkeypatch.setenv("REVIT_PORT", "50000")
    assert await config.resolve_port_async() == 50000
    assert attempts == []  # no probing at all


async def test_live_port_cached(monkeypatch):
    attempts = []

    def handler(request):
        if request.url.port == 48885:
            return httpx.Response(200)
        raise httpx.ConnectError("refused", request=request)

    _install_transport(monkeypatch, handler, attempts)
    assert await config.resolve_port_async() == 48885
    attempts.clear()
    assert await config.resolve_port_async() == 48885
    assert attempts == []  # served from cache


async def test_all_dead_sets_negative_cache(monkeypatch):
    attempts = []

    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    _install_transport(monkeypatch, handler, attempts)
    assert await config.resolve_port_async() == config.DEFAULT_PORTS[0]
    assert len(attempts) == len(config.DEFAULT_PORTS)
    attempts.clear()
    # within TTL: zero HTTP attempts
    assert await config.resolve_port_async() == config.DEFAULT_PORTS[0]
    assert attempts == []


async def test_negative_cache_expires(monkeypatch):
    attempts = []

    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    _install_transport(monkeypatch, handler, attempts)
    await config.resolve_port_async()
    attempts.clear()

    # Jump the clock past the TTL
    import time as time_mod
    real_monotonic = time_mod.monotonic
    monkeypatch.setattr(
        "revit_mcp_server.config.time.monotonic",
        lambda: real_monotonic() + config.NEGATIVE_CACHE_TTL + 1,
    )
    await config.resolve_port_async()
    assert len(attempts) == len(config.DEFAULT_PORTS)  # re-probed


async def test_invalidate_keeps_negative_cache(monkeypatch):
    attempts = []

    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    _install_transport(monkeypatch, handler, attempts)
    await config.resolve_port_async()  # arms the negative cache
    attempts.clear()

    config.invalidate_port_cache()  # what _revit_call's retry path does
    await config.resolve_port_async()
    assert attempts == []  # retry fails fast, no second probe round
