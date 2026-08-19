# -*- coding: utf-8 -*-
"""Per-machine settings: %LOCALAPPDATA%/revit-mcp/config.json.

Currently one key: report_dir — the team telemetry drop folder (a synced
SharePoint/OneDrive library or a UNC share). Kept out of the public repo on
purpose: internal paths are configured per machine, never published.
"""
import json
import os


def _path():
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(root, "revit-mcp", "config.json")


def load():
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
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
