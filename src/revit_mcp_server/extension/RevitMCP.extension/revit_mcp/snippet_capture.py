# -*- coding: UTF-8 -*-
"""Snippet capture at the point of execution — inside Revit.

Capturing in the MCP server proved unreliable: AI clients sandbox the server
process (Codex denies writes outside its workspace via ACLs and strips the
environment), so records were silently lost. The Revit process runs as the
user with full rights and no client sandbox — captured here, a record can
always land.

Enabled by "snippet_capture": true in %LOCALAPPDATA%/revit-mcp/config.json
(written by `revit-mcp install`); the file is read per call so toggling does
not require a Revit restart. Schema matches the server-side snippet log v1.
Every failure is swallowed: telemetry must never break code execution.

IronPython 2.7 module — no f-strings, no annotations.
"""
import hashlib
import json
import os
from datetime import datetime

SCHEMA_VERSION = 1


def _data_root():
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        profile = os.environ.get("USERPROFILE")
        if profile:
            root = os.path.join(profile, "AppData", "Local")
    if not root:
        return None
    return os.path.join(root, "revit-mcp")


def is_enabled():
    root = _data_root()
    if not root:
        return False
    try:
        f = open(os.path.join(root, "config.json"), "r")
        try:
            cfg = json.load(f)
        finally:
            f.close()
        return bool(cfg.get("snippet_capture"))
    except Exception:
        return False


def _normalize(code):
    lines = []
    for line in code.strip().splitlines():
        if line.strip():
            lines.append(line.rstrip())
    return "\n".join(lines)


def snippet_hash(code):
    return hashlib.sha256(_normalize(code).encode("utf-8")).hexdigest()[:16]


def capture(code, description, session, ok, duration_ms, output_chars):
    """Append one record. Returns True if written, False otherwise."""
    if not is_enabled():
        return False
    try:
        root = _data_root()
        if root is None:
            return False
        now = datetime.utcnow()
        record = {
            "v": SCHEMA_VERSION,
            "ts": now.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "session": session or "revit",
            "hash": snippet_hash(code),
            "code": code,
            "description": description,
            "ok": bool(ok),
            "route_ok": bool(ok),
            "duration_ms": int(duration_ms),
            "output_chars": int(output_chars),
        }
        path = os.path.join(
            root, "snippets", "snippets-{}.jsonl".format(now.strftime("%Y%m"))
        )
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        f = open(path, "a")
        try:
            f.write(json.dumps(record) + "\n")
        finally:
            f.close()
        return True
    except Exception:
        return False
