# -*- coding: utf-8 -*-
"""Per-machine settings: %LOCALAPPDATA%/revit-mcp/config.json.

Keys: report_dir — the team telemetry drop folder (a synced
SharePoint/OneDrive library or a UNC share); snippet_capture — the
Revit-side capture switch (read per call by the extension);
sql_connection — ODBC string for the optional SQL Server mirror
(see sql_push.py). All kept out of the public repo on purpose: internal
paths and connection strings are configured per machine, never published.
"""
import json
import os


def _path():
    from .paths import data_root

    root = data_root()
    if root is None:
        raise RuntimeError(
            "cannot resolve a local data directory (no LOCALAPPDATA/USERPROFILE)"
        )
    return os.path.join(root, "config.json")


def load():
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, RuntimeError):
        return {}


def save(**updates):
    data = load()
    data.update(updates)
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def report_dir():
    value = load().get("report_dir")
    return value if value and isinstance(value, str) else None
