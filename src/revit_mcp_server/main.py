# -*- coding: utf-8 -*-
import sys
import base64
from typing import Optional, Dict, Any, Union

import anyio
import httpx
from mcp.server.mcpserver import Image, Context

from . import config
from .usage_log import LoggingMCPServer

def _package_version():
    try:
        from importlib.metadata import version
        return version("revit-mcp")
    except Exception:
        return ""


# Create a generic MCP server for interacting with Revit. Transport settings
# (host/port, stateless_http, json_response) moved to run()/the app factories
# in MCP SDK 2.0, so the constructor only names the server. SDK 2.0 reports an
# empty serverInfo.version unless one is passed explicitly.
mcp = LoggingMCPServer("Revit MCP Server", version=_package_version())

# Shared HTTP transport settings: stateless_http/json_response for better
# client compatibility, loopback-only bind.
_HTTP_HOST = "127.0.0.1"


async def revit_get(endpoint: str, ctx: Context = None, **kwargs) -> Union[Dict, str]:
    """Simple GET request to Revit API"""
    return await _revit_call("GET", endpoint, ctx=ctx, **kwargs)


async def revit_post(endpoint: str, data: Dict[str, Any], ctx: Context = None, **kwargs) -> Union[Dict, str]:
    """Simple POST request to Revit API"""
    return await _revit_call("POST", endpoint, data=data, ctx=ctx, **kwargs)


async def revit_image(endpoint: str, ctx: Context = None) -> Union[Image, str]:
    """GET request that returns an Image object"""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(f"{config.base_url()}{endpoint}")

            if response.status_code == 200:
                data = response.json()
                image_bytes = base64.b64decode(data["image_data"])
                return Image(data=image_bytes, format="png")
            else:
                return f"Error: {response.status_code} - {response.text}"
    except httpx.TimeoutException:
        return "Error: Image export timed out after 60 seconds."
    except Exception as e:
        msg = str(e) or type(e).__name__
        return f"Error: {msg}"


async def _revit_call(method: str, endpoint: str, data: Dict = None, ctx: Context = None,
                     timeout: float = 30.0, params: Dict = None) -> Union[Dict, str]:
    """Internal function handling all HTTP calls.

    On a connection failure the cached port is invalidated and the call retried
    once — Revit may have restarted on the next port in the range (48884-48887).
    """
    try:
        try:
            return await _do_call(method, endpoint, data, timeout, params)
        except httpx.ConnectError:
            config.invalidate_port_cache()
            return await _do_call(method, endpoint, data, timeout, params)
    except httpx.TimeoutException:
        return f"Error: Request timed out after {timeout} seconds. The operation may still be running in Revit."
    except Exception as e:
        msg = str(e) or type(e).__name__
        return f"Error: {msg}"


async def _do_call(method: str, endpoint: str, data: Dict = None,
                   timeout: float = 30.0, params: Dict = None) -> Union[Dict, str]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        url = f"{config.base_url()}{endpoint}"

        if method == "GET":
            response = await client.get(url, params=params)
        else:  # POST
            response = await client.post(url, json=data, headers={"Content-Type": "application/json"})

        return response.json() if response.status_code == 200 else f"Error: {response.status_code} - {response.text}"


# Register all tools BEFORE the main block
from .tools import register_tools
register_tools(mcp, revit_get, revit_post, revit_image)


async def run_combined_async():
    """Run server with both SSE and streamable-http endpoints.

    This allows clients to connect via either:
    - SSE: GET /sse, POST /messages/
    - Streamable-HTTP: POST/GET /mcp
    """
    import uvicorn

    # Get the streamable-http app first - it has the proper lifespan
    # that initializes the session manager's task group
    http_app = mcp.streamable_http_app(stateless_http=True, json_response=True)

    # Get SSE routes (SSE doesn't need special lifespan - it creates
    # task groups per-request in connect_sse())
    sse_app = mcp.sse_app()

    # Add SSE routes to the http app (preserving its lifespan)
    for route in sse_app.routes:
        http_app.routes.append(route)

    config_ = uvicorn.Config(
        http_app,
        host=_HTTP_HOST,
        port=config.http_port(),
        log_level=mcp.settings.log_level.lower(),
    )
    server = uvicorn.Server(config_)
    await server.serve()


def run_server(argv=None):
    """Entry point used by the CLI (`revit-mcp serve`)."""
    argv = sys.argv[1:] if argv is None else argv

    if "--sse" in argv:
        mcp.run(transport="sse", host=_HTTP_HOST, port=config.http_port())
    elif "--http" in argv or "--streamable-http" in argv:
        mcp.run(
            transport="streamable-http",
            host=_HTTP_HOST,
            port=config.http_port(),
            stateless_http=True,
            json_response=True,
        )
    elif "--combined" in argv:
        # Run both SSE and streamable-http transports simultaneously
        print("Starting combined server with SSE (/sse, /messages/) and streamable-http (/mcp) endpoints...")
        anyio.run(run_combined_async)
        sys.exit(0)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
