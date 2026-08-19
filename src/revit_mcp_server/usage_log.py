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
    from .paths import data_root

    root = data_root()
    if root is None:
        return None  # no resolvable home: skip logging, never write relative
    return os.path.join(root, "usage", "usage-{:%Y%m}.jsonl".format(now))


def classify_result(result):
    """Truthful route-level outcome, derived from the tool's return value.

    Route failures come back as strings ("Error: 500 - ...") or formatted
    error blocks, never exceptions — so `ok` alone mislabels them. Heuristic:
    a legitimate output that happens to start with "Error:" logs a false
    negative; accepted, this only feeds stats ranking.
    """
    if isinstance(result, str):
        return not (
            result.startswith("Error:") or "=== ERROR DETAILS ===" in result
        )
    if isinstance(result, dict):
        return not result.get("error")
    return True


def log_usage(tool_name, kwargs, ok, duration_s, error_type=None, route_ok=None):
    if not _enabled():
        return
    try:
        from .runtime import SESSION_ID

        now = datetime.now(timezone.utc)
        record = {
            "v": SCHEMA_VERSION,
            "ts": now.isoformat(timespec="seconds"),
            "session": SESSION_ID,
            "tool": tool_name,
            "args_shape": {
                k: type(v).__name__ for k, v in kwargs.items() if k != "ctx"
            },
            "ok": ok,
            "duration_ms": round(duration_s * 1000),
        }
        if route_ok is not None:
            record["route_ok"] = route_ok
        if error_type:
            record["error_type"] = error_type
        path = _log_path(now)
        if path is None:
            return
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
                route_ok = None
                try:
                    result = await fn(*f_args, **f_kwargs)
                    route_ok = classify_result(result)
                    return result
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
                        route_ok,
                    )

            return register(logged)

        return wrapper
