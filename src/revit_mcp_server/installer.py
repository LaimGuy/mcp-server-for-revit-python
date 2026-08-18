# -*- coding: utf-8 -*-
"""`revit-mcp install` / `revit-mcp uninstall`.

Copies the bundled pyRevit extension into place, makes the two config edits
pyRevit needs (surgical line edits - pyRevit_config.ini's formatting does not
survive a configparser round-trip), and wires the MCP client configs so the
user never touches JSON or absolute paths by hand.
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
from importlib import resources

from . import SOURCE_URL, __version__

EXTENSION_NAME = "RevitMCP.extension"
VERSION_MARKER = ".revit_mcp_version"


def _appdata():
    return os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")


def pyrevit_dir():
    return os.path.join(_appdata(), "pyRevit")


def ini_path():
    return os.path.join(pyrevit_dir(), "pyRevit_config.ini")


def extensions_dir():
    return os.path.join(pyrevit_dir(), "Extensions")


def _confirm(question, assume_yes):
    if assume_yes:
        print(f"  {question} -> yes (--yes)")
        return True
    if not sys.stdin.isatty():
        print(f"  {question} -> no (non-interactive; pass --yes to accept)")
        return False
    try:
        answer = input(f"  {question} [Y/n] ").strip().lower()
    except EOFError:
        # isatty() can lie under process runners; EOF means nobody is answering
        print("  -> no (stdin closed; pass --yes to accept)")
        return False
    return answer in ("", "y", "yes")


# --- ini surgery -----------------------------------------------------------

def _read_ini_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().splitlines()


def _write_ini_lines(path, lines):
    backup = "{}.bak-{}".format(path, datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path, backup)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  Edited {path} (backup: {os.path.basename(backup)})")


def _section_bounds(lines, section):
    """Return (header_index, end_index) of [section], or (None, None)."""
    header = "[{}]".format(section)
    start = None
    for i, line in enumerate(lines):
        if line.strip() == header:
            start = i
            break
    if start is None:
        return None, None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            end = i
            break
    return start, end


def set_ini_value(lines, section, key, value):
    """Set key = value inside [section], appending section/key as needed.

    Returns (lines, changed).
    """
    start, end = _section_bounds(lines, section)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["[{}]".format(section), "{} = {}".format(key, value)])
        return lines, True
    for i in range(start + 1, end):
        stripped = lines[i].strip()
        if stripped.startswith(key) and stripped[len(key):].lstrip().startswith("="):
            new_line = "{} = {}".format(key, value)
            if lines[i].strip() == new_line:
                return lines, False
            lines[i] = new_line
            return lines, True
    lines.insert(end, "{} = {}".format(key, value))
    return lines, True


def get_ini_value(lines, section, key):
    start, end = _section_bounds(lines, section)
    if start is None:
        return None
    for i in range(start + 1, end):
        stripped = lines[i].strip()
        if stripped.startswith(key) and stripped[len(key):].lstrip().startswith("="):
            return stripped.split("=", 1)[1].strip()
    return None


# --- extension payload -----------------------------------------------------

def _bundled_extension():
    return resources.files("revit_mcp_server") / "extension" / EXTENSION_NAME


def install_extension(assume_yes):
    target = os.path.join(extensions_dir(), EXTENSION_NAME)
    if os.path.isdir(target):
        installed = _installed_version(target)
        if not _confirm(
            f"{EXTENSION_NAME} already installed (v{installed or 'unknown'}); replace with v{__version__}?",
            assume_yes,
        ):
            print("  Keeping the existing extension.")
            return target
        shutil.rmtree(target)
    os.makedirs(extensions_dir(), exist_ok=True)
    with resources.as_file(_bundled_extension()) as src:
        shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    with open(os.path.join(target, VERSION_MARKER), "w", encoding="utf-8") as f:
        f.write(__version__ + "\n")
    print(f"  Installed extension -> {target}")
    return target


def _installed_version(ext_dir):
    try:
        with open(os.path.join(ext_dir, VERSION_MARKER), "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


# --- collision check -------------------------------------------------------

def _user_extension_paths(lines):
    raw = get_ini_value(lines, "core", "userextensions")
    if not raw:
        return []
    try:
        return [p for p in json.loads(raw) if os.path.isdir(p)]
    except (ValueError, TypeError):
        return []


def find_colliding_extensions(lines):
    """Other installed extensions that register routes.API("revit_mcp")."""
    roots = [extensions_dir()] + _user_extension_paths(lines)
    collisions = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for entry in os.listdir(root):
            if not entry.endswith(".extension") or entry == EXTENSION_NAME:
                continue
            startup = os.path.join(root, entry, "startup.py")
            try:
                with open(startup, "r", encoding="utf-8", errors="replace") as f:
                    if 'routes.API("revit_mcp")' in f.read():
                        collisions.append(entry)
            except OSError:
                continue
    return collisions


# --- client wiring ---------------------------------------------------------

def _uvx_path():
    found = shutil.which("uvx")
    if found:
        return found
    fallback = os.path.join(os.path.expanduser("~"), ".local", "bin", "uvx.exe")
    return fallback if os.path.isfile(fallback) else "uvx"


def _server_command():
    return [_uvx_path(), "--from", SOURCE_URL, "revit-mcp"]


CAPTURE_ENV = "REVIT_MCP_SNIPPET_LOG"


def wire_claude(assume_yes, capture=False):
    cmd = ["claude", "mcp", "add", "revit", "-s", "user"]
    if capture:
        cmd += ["-e", f"{CAPTURE_ENV}=1"]
    cmd += ["--"] + _server_command()
    printable = " ".join(cmd)
    if shutil.which("claude") is None:
        print("  Claude Code CLI not found on PATH. Run this yourself once it is installed:")
        print(f"    {printable}")
        return
    if not _confirm("Register with Claude Code (claude mcp add revit -s user)?", assume_yes):
        print(f"  Skipped. To do it later:\n    {printable}")
        return
    # Remove first so re-running install upgrades an existing entry (e.g. to
    # gain the capture env). Failure just means it wasn't there yet.
    subprocess.run(["claude", "mcp", "remove", "revit", "-s", "user"],
                   capture_output=True, text=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        note = " with snippet capture" if capture else ""
        print(f"  Claude Code: registered MCP server 'revit' (user scope){note}.")
    else:
        print(f"  claude mcp add failed ({result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
        print(f"  Run it manually:\n    {printable}")


CODEX_SECTION_NAMES = ("mcp_servers.revit", "mcp_servers.revitmcp")


def _toml_table_present(lines, name):
    """True if [name] or any [name.sub...] table exists."""
    for line in lines:
        stripped = line.strip()
        if stripped == "[{}]".format(name) or stripped.startswith("[{}.".format(name)):
            return True
    return False


def _remove_toml_table(lines, name):
    """Remove [name] AND every [name.sub...] table.

    Leaving a sub-table behind (e.g. [mcp_servers.x.tools.y]) implicitly
    recreates the parent table with no command/url, which Codex rejects as
    'invalid transport'.
    """
    out, skipping = [], False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            header = stripped.strip("[]")
            skipping = header == name or header.startswith(name + ".")
        if not skipping:
            out.append(line)
    return out


def _codex_env_line():
    return 'env = {{ "{}" = "1" }}'.format(CAPTURE_ENV)


def _codex_toml_snippet(capture=False):
    uvx = _uvx_path().replace("\\", "\\\\")
    snippet = (
        "[mcp_servers.revit]\n"
        f'command = "{uvx}"\n'
        f'args = ["--from", "{SOURCE_URL}", "revit-mcp"]\n'
    )
    if capture:
        snippet += _codex_env_line() + "\n"
    return snippet


def _codex_revit_has_env(lines):
    start, end = _section_bounds(lines, "mcp_servers.revit")
    if start is None:
        return False
    return any(CAPTURE_ENV in lines[i] for i in range(start + 1, end))


def wire_codex(assume_yes, capture=False):
    config_path = os.path.join(os.path.expanduser("~"), ".codex", "config.toml")
    snippet = _codex_toml_snippet(capture)
    if not os.path.isfile(config_path):
        print("  Codex config not found; if you use Codex, add to ~/.codex/config.toml:")
        print("    " + snippet.replace("\n", "\n    "))
        return

    with open(config_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    current_ok = _toml_table_present(lines, "mcp_servers.revit")
    if current_ok and not _toml_table_present(lines, "mcp_servers.revitmcp"):
        # Entry exists. Upgrade in place if capture wiring is the only gap —
        # a full replace would discard the user's per-tool approval
        # sub-tables, which survive an env insertion.
        if capture and not _codex_revit_has_env(lines):
            if _confirm("Enable snippet capture in the existing Codex entry?", assume_yes):
                start, end = _section_bounds(lines, "mcp_servers.revit")
                insert_at = end
                for i in range(start + 1, end):
                    if lines[i].strip().startswith("args"):
                        insert_at = i + 1
                        break
                lines.insert(insert_at, _codex_env_line())
                _write_ini_lines(config_path, lines)
                print("  Codex: snippet capture enabled on existing entry.")
        else:
            print("  Codex: [mcp_servers.revit] already configured.")
        return

    stale = [name for name in CODEX_SECTION_NAMES
             if _toml_table_present(lines, name)]
    if stale:
        if not _confirm(f"Codex already has {stale}; replace with the packaged server?", assume_yes):
            print("  Left Codex config unchanged.")
            return
        for name in stale:
            lines = _remove_toml_table(lines, name)
    elif not _confirm("Add the server to Codex (~/.codex/config.toml)?", assume_yes):
        print("  Skipped. Snippet for later:")
        print("    " + snippet.replace("\n", "\n    "))
        return

    if lines and lines[-1].strip():
        lines.append("")
    lines.extend(snippet.splitlines())
    _write_ini_lines(config_path, lines)  # same backup+write mechanics as the ini
    print("  Codex: [mcp_servers.revit] configured.")


# --- commands --------------------------------------------------------------

def run_install(args):
    print(f"revit-mcp {__version__} - install")

    if not os.path.isdir(pyrevit_dir()) or not os.path.isfile(ini_path()):
        print("pyRevit not found (%APPDATA%\\pyRevit missing). Install pyRevit first:")
        print("  https://pyrevitlabs.io/")
        return 1

    print("[1/4] pyRevit extension")
    install_extension(args.yes)

    lines = _read_ini_lines(ini_path())
    changed = False

    print("[2/4] Extension conflicts")
    collisions = find_colliding_extensions(lines)
    for name in collisions:
        section = name  # pyRevit uses the folder name as the ini section
        if get_ini_value(lines, section, "disabled") == "true":
            print(f"  {name}: already disabled - ok.")
            continue
        print(f"  {name} also registers the revit_mcp routes API; both enabled would")
        print("  double-register every route when Revit starts.")
        if _confirm(f"Disable {name} in pyRevit_config.ini?", args.yes):
            lines, c = set_ini_value(lines, section, "disabled", "true")
            changed = changed or c
        else:
            print(f"  WARNING: leaving {name} enabled - disable one of the two before starting Revit.")
    if not collisions:
        print("  None found.")

    print("[3/4] pyRevit Routes server")
    routes_enabled = get_ini_value(lines, "routes", "enabled")
    if routes_enabled == "true":
        print("  Already enabled.")
    else:
        lines, c = set_ini_value(lines, "routes", "enabled", "true")
        changed = changed or c
        print("  Enabled ([routes] enabled = true).")

    if changed:
        _write_ini_lines(ini_path(), lines)

    print("[4/4] MCP clients")
    capture = False
    if args.client != "none":
        print("  Snippet capture records the code passed to execute_revit_code")
        print("  to a local file (nothing leaves this machine). It feeds the")
        print("  tool-improvement pipeline (revit-mcp stats / promote).")
        capture = _confirm("Enable snippet capture?", args.yes)
    if args.client in ("claude", "both"):
        wire_claude(args.yes, capture)
    if args.client in ("codex", "both"):
        wire_codex(args.yes, capture)
    if args.client == "none":
        print("  Skipped (--client none). Server command:")
        print("    " + " ".join(_server_command()))

    print()
    print("Done. Next steps:")
    print("  1. Restart Revit (the extension loads at startup).")
    print(f"  2. Verify: {_uvx_path()} --from {SOURCE_URL} revit-mcp doctor")
    return 0


def run_update(args):
    """Non-interactive refresh: re-copy the extension at this package version.

    Client configs are left alone (they point at the same source URL, which
    always serves the current release), so update is just extension + marker.
    """
    print(f"revit-mcp {__version__} - update")
    target = os.path.join(extensions_dir(), EXTENSION_NAME)
    old = _installed_version(target) if os.path.isdir(target) else None
    if old == __version__:
        print(f"  Already at v{__version__}.")
        return 0
    if not os.path.isdir(pyrevit_dir()):
        print("pyRevit not found; run: revit-mcp install")
        return 1
    if os.path.isdir(target):
        shutil.rmtree(target)
    os.makedirs(extensions_dir(), exist_ok=True)
    with resources.as_file(_bundled_extension()) as src:
        shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    with open(os.path.join(target, VERSION_MARKER), "w", encoding="utf-8") as f:
        f.write(__version__ + "\n")
    print(f"  Extension updated: v{old or 'none'} -> v{__version__}")
    print("  Restart Revit to load the new version.")
    _report_missing_capture()
    return 0


def _report_missing_capture():
    """Update never edits client configs; it just points at install."""
    missing = []
    claude_json = os.path.join(os.path.expanduser("~"), ".claude.json")
    try:
        with open(claude_json, "r", encoding="utf-8") as f:
            revit = (json.load(f).get("mcpServers") or {}).get("revit")
        if revit is not None and CAPTURE_ENV not in (revit.get("env") or {}):
            missing.append("Claude Code")
    except (OSError, ValueError):
        pass
    codex_toml = os.path.join(os.path.expanduser("~"), ".codex", "config.toml")
    try:
        with open(codex_toml, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        if _toml_table_present(lines, "mcp_servers.revit") and not _codex_revit_has_env(lines):
            missing.append("Codex")
    except OSError:
        pass
    if missing:
        print("  Snippet capture is not wired for: {}. To enable, re-run:".format(
            ", ".join(missing)))
        print("    {} --from {} revit-mcp install".format(_uvx_path(), SOURCE_URL))


def run_uninstall(args):
    print(f"revit-mcp {__version__} - uninstall")
    target = os.path.join(extensions_dir(), EXTENSION_NAME)
    if os.path.isdir(target):
        if _confirm(f"Remove {target}?", args.yes):
            shutil.rmtree(target)
            print("  Extension removed.")
    else:
        print("  Extension not installed.")

    if shutil.which("claude") is not None:
        if _confirm("Remove 'revit' from Claude Code (claude mcp remove revit -s user)?", args.yes):
            subprocess.run(["claude", "mcp", "remove", "revit", "-s", "user"],
                           capture_output=True, text=True)
            print("  Claude Code entry removed.")
    print("  If you use Codex, delete the [mcp_servers.revit] block from ~/.codex/config.toml.")
    print("  pyRevit's [routes] setting and other extensions were left untouched.")
    return 0
