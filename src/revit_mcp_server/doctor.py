# -*- coding: utf-8 -*-
"""`revit-mcp doctor` - walk the whole chain and say exactly what's broken."""
import json
import os
import shutil
import sys

import httpx

from . import __version__
from . import config
from .installer import (
    EXTENSION_NAME,
    VERSION_MARKER,
    _installed_version,
    _read_ini_lines,
    extensions_dir,
    find_colliding_extensions,
    get_ini_value,
    ini_path,
    pyrevit_dir,
)

_RESULTS = {"FAIL": 0, "WARN": 0}


def _report(level, message, fix=None):
    print(f"[{level}] {message}")
    if fix:
        print(f"       fix: {fix}")
    if level in _RESULTS:
        _RESULTS[level] += 1


def run_doctor():
    print(f"revit-mcp {__version__} - doctor")

    # 1. Interpreter / uv
    py = sys.version_info
    if py >= (3, 11):
        _report("PASS", f"Python {py.major}.{py.minor}.{py.micro}")
    else:
        _report("FAIL", f"Python {py.major}.{py.minor} < 3.11",
                "install a newer Python (uv brings its own: uv python install 3.13)")
    uvx = shutil.which("uvx")
    _report("PASS" if uvx else "WARN",
            f"uvx: {uvx or 'not on PATH'}",
            None if uvx else "irm https://astral.sh/uv/install.ps1 | iex, then open a new terminal")

    # 2. pyRevit
    if not os.path.isfile(ini_path()):
        _report("FAIL", f"pyRevit not found ({pyrevit_dir()})",
                "install pyRevit from https://pyrevitlabs.io/ and run it once in Revit")
        return _summary()
    _report("PASS", f"pyRevit config: {ini_path()}")

    # 3. Extension installed
    ext_dir = os.path.join(extensions_dir(), EXTENSION_NAME)
    if not os.path.isdir(ext_dir):
        _report("FAIL", f"{EXTENSION_NAME} not installed",
                "run: revit-mcp install")
        installed = None
    else:
        installed = _installed_version(ext_dir)
        if installed == __version__:
            _report("PASS", f"{EXTENSION_NAME} v{installed} installed")
        else:
            _report("WARN", f"{EXTENSION_NAME} v{installed or '?'} != package v{__version__}",
                    "re-run: revit-mcp install (then restart Revit)")

    # 4. Collisions
    lines = _read_ini_lines(ini_path())
    live_collisions = [
        name for name in find_colliding_extensions(lines)
        if get_ini_value(lines, name, "disabled") != "true"
    ]
    if live_collisions:
        _report("FAIL", f"conflicting extension(s) enabled: {', '.join(live_collisions)}",
                "revit-mcp install offers to disable them, or set disabled = true in pyRevit_config.ini")
    else:
        _report("PASS", "no conflicting revit_mcp extensions enabled")

    # 5. Routes enabled
    if get_ini_value(lines, "routes", "enabled") == "true":
        _report("PASS", "[routes] enabled = true")
    else:
        _report("FAIL", "pyRevit Routes server disabled",
                "run: revit-mcp install (or pyRevit Settings -> Routes -> enable), then restart Revit")

    ini_port = get_ini_value(lines, "routes", "port")
    ports = [int(ini_port)] if ini_port else list(config.DEFAULT_PORTS)

    # 6. Live probe
    live_port, status_code = None, None
    for port in ports:
        try:
            r = httpx.get(f"http://{config.get_host()}:{port}/revit_mcp/status/", timeout=2.0)
            if r.status_code in (200, 503):
                live_port, status_code = port, r.status_code
                break
        except httpx.HTTPError:
            continue
    if live_port is None:
        _report("FAIL", f"Revit not reachable on ports {ports}",
                "start Revit; if it is running, restart it so the extension and Routes load")
        return _summary()
    doc_state = "document open" if status_code == 200 else "no document open (fine)"
    _report("PASS", f"Revit answering on port {live_port} - {doc_state}")

    # 7. Manifest
    try:
        r = httpx.get(f"http://{config.get_host()}:{live_port}/revit_mcp/tools/", timeout=5.0)
        manifest = r.json() if r.status_code == 200 else None
    except (httpx.HTTPError, json.JSONDecodeError):
        manifest = None
    if manifest and manifest.get("manifest_version") == 1:
        _report("PASS", f"manifest v1: {len(manifest.get('tools', []))} tools declared")
    else:
        _report("WARN", "GET /revit_mcp/tools/ missing or unversioned",
                "extension predates the manifest - re-run revit-mcp install and restart Revit")

    # 8. Client configs
    claude_json = os.path.join(os.path.expanduser("~"), ".claude.json")
    claude_ok = False
    try:
        with open(claude_json, "r", encoding="utf-8") as f:
            claude_ok = "revit" in (json.load(f).get("mcpServers") or {})
    except (OSError, ValueError):
        pass
    _report("PASS" if claude_ok else "WARN",
            "Claude Code: 'revit' " + ("configured (user scope)" if claude_ok else "not in ~/.claude.json mcpServers"),
            None if claude_ok else "run: revit-mcp install  (or: claude mcp add revit -s user -- uvx --from <source> revit-mcp)")

    codex_toml = os.path.join(os.path.expanduser("~"), ".codex", "config.toml")
    codex_ok = False
    try:
        with open(codex_toml, "r", encoding="utf-8") as f:
            codex_ok = "[mcp_servers.revit]" in f.read()
    except OSError:
        pass
    _report("PASS" if codex_ok else "WARN",
            "Codex: [mcp_servers.revit] " + ("configured" if codex_ok else "not in ~/.codex/config.toml"),
            None if codex_ok else "run: revit-mcp install --client codex")

    return _summary()


def _summary():
    print()
    if _RESULTS["FAIL"]:
        print(f"{_RESULTS['FAIL']} failure(s), {_RESULTS['WARN']} warning(s).")
        return 1
    if _RESULTS["WARN"]:
        print(f"All checks passed with {_RESULTS['WARN']} warning(s).")
        return 0
    print("All checks passed.")
    return 0
