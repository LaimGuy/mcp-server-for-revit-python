# -*- coding: utf-8 -*-
"""Perf regression guard: the HTTP client must be shared, not per-call.

A per-call AsyncClient costs ~750ms each (eager certifi/SSL-context load) for
plaintext loopback traffic. If these tests start failing, that regression is
back.
"""
import httpx
import pytest

from revit_mcp_server import config, http_client
from revit_mcp_server import main


@pytest.fixture(autouse=True)
def _pin_port(monkeypatch):
    # Pin the port so _do_call never probes.
    monkeypatch.setenv("REVIT_PORT", "48884")


async def test_client_constructed_once_across_calls(monkeypatch):
    constructed = []
    real_init = httpx.AsyncClient.__init__

    def counting_init(self, *args, **kwargs):
        constructed.append(kwargs)
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": "ok"})
        )
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", counting_init)
    http_client.reset_client()

    first = await main._do_call("GET", "/status/")
    second = await main._do_call("GET", "/status/")

    assert first == {"status": "ok"}
    assert second == {"status": "ok"}
    assert len(constructed) == 1, "AsyncClient must be constructed exactly once"


async def test_client_skips_tls_verification_for_loopback():
    http_client.reset_client()
    client = http_client.get_client()
    assert client is http_client.get_client()  # same instance back


def test_reset_client_forces_rebuild():
    http_client.reset_client()
    # Outside a running loop get_client still works (lazy loop binding).
    a = http_client.get_client()
    http_client.reset_client()
    b = http_client.get_client()
    assert a is not b
