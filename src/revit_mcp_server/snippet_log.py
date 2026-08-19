# -*- coding: utf-8 -*-
"""Snippet capture — schema v1. The raw material of the tool-learning loop.

UNLIKE the usage log (types only, on by default), this sink stores the actual
code and description passed to execute_revit_code, so it is OPT-IN:
set REVIT_MCP_SNIPPET_LOG=1 to enable. Separate env var, separate directory:
%LOCALAPPDATA%/revit-mcp/snippets/snippets-YYYYMM.jsonl

One JSON line per execute_revit_code call:
    {v, ts, session, hash, code, description, ok, route_ok, duration_ms,
     output_chars}

hash is sha256 of whitespace-normalized code, truncated to 16 hex chars —
stable across whitespace-only retries, so repeated runs of the same logic
cluster under one key. `revit-mcp stats` aggregates these; `revit-mcp promote
<hash>` turns one into a named tool.

Failures here are swallowed: telemetry must never break a tool call.
"""
import hashlib
import json
import os
from datetime import datetime, timezone

from .runtime import SESSION_ID

SCHEMA_VERSION = 1


def _enabled():
    return os.environ.get("REVIT_MCP_SNIPPET_LOG", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def normalize_code(code):
    """Whitespace-normalized form used for hashing."""
    return "\n".join(
        line.rstrip() for line in code.strip().splitlines() if line.strip()
    )


def snippet_hash(code):
    return hashlib.sha256(normalize_code(code).encode("utf-8")).hexdigest()[:16]


def classify_route_response(response):
    """Truthful outcome: did the code actually run in Revit successfully?

    _revit_call converts Revit-side HTTP 500s into "Error: ..." strings, so
    exceptions alone are a useless signal.
    """
    if isinstance(response, dict):
        if response.get("error"):
            return False
        status = str(response.get("status", "")).lower()
        if status in ("error", "failed", "failure", "exception"):
            return False
        return True
    if isinstance(response, str):
        return not response.startswith("Error:")
    return False


def _log_path(now):
    from .paths import data_root

    root = data_root()
    if root is None:
        return None  # no resolvable home: skip logging, never write relative
    return os.path.join(root, "snippets", "snippets-{:%Y%m}.jsonl".format(now))


def log_snippet(code, description, response, duration_s):
    if not _enabled():
        return
    try:
        now = datetime.now(timezone.utc)
        output = ""
        if isinstance(response, dict):
            output = str(response.get("output", ""))
        record = {
            "v": SCHEMA_VERSION,
            "ts": now.isoformat(timespec="seconds"),
            "session": SESSION_ID,
            "hash": snippet_hash(code),
            "code": code,
            "description": description,
            "ok": True,
            "route_ok": classify_route_response(response),
            "duration_ms": round(duration_s * 1000),
            "output_chars": len(output),
        }
        path = _log_path(now)
        if path is None:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass
