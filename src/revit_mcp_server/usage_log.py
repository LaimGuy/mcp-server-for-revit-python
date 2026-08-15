# -*- coding: utf-8 -*-
"""Local usage telemetry — the phase-B/C contract (schema v1).

One JSON line per tool call to %LOCALAPPDATA%/revit-mcp/usage/usage-YYYYMM.jsonl:

    {"ts", "tool", "args_shape", "ok", "duration_ms", "error_type"}

args_shape maps argument names to *type names only* — never values, paths, or
model data. Opt out with REVIT_MCP_USAGE_LOG=0. Logging must never break a tool
call: every failure here is swallowed.
"""
import functools
import json
import os
import time
from datetime import datetime, timezone

from mcp.server.mcpserver import MCPServer

SCHEMA_VERSION = 1


def _enabled():
    return os.environ.get("REVIT_MCP_USAGE_LOG", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _log_path(now):
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(
        root, "revit-mcp", "usage", "usage-{:%Y%m}.jsonl".format(now)
    )


def log_usage(tool_name, kwargs, ok, duration_s, error_type=None):
    if not _enabled():
        return
    try:
        now = datetime.now(timezone.utc)
        record = {
            "v": SCHEMA_VERSION,
            "ts": now.isoformat(timespec="seconds"),
            "tool": tool_name,
            "args_shape": {
                k: type(v).__name__ for k, v in kwargs.items() if k != "ctx"
            },
            "ok": ok,
            "duration_ms": round(duration_s * 1000),
        }
        if error_type:
            record["error_type"] = error_type
        path = _log_path(now)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


class LoggingMCPServer(MCPServer):
    """MCPServer that records a usage line for every registered tool call.

    Wraps at registration so tools/*.py stay untouched. functools.wraps keeps
    __wrapped__/annotations intact, so the SDK's signature-based schema
    generation and Context injection see the original function.
    """

    def tool(self, *args, **kwargs):
        register = super().tool(*args, **kwargs)

        def wrapper(fn):
            @functools.wraps(fn)
            async def logged(*f_args, **f_kwargs):
                start = time.monotonic()
                error_type = None
                try:
                    return await fn(*f_args, **f_kwargs)
                except Exception as exc:
                    error_type = type(exc).__name__
                    raise
                finally:
                    log_usage(
                        fn.__name__,
                        f_kwargs,
                        error_type is None,
                        time.monotonic() - start,
                        error_type,
                    )

            return register(logged)

        return wrapper
