# -*- coding: utf-8 -*-
"""One version, three places — this test is the release-checklist enforcer."""
import os
import tomllib

from revit_mcp_server import __version__

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_pyproject_matches_package():
    with open(os.path.join(REPO_ROOT, "pyproject.toml"), "rb") as f:
        pyproject = tomllib.load(f)
    assert pyproject["project"]["version"] == __version__


def test_extension_version_file_matches_package():
    path = os.path.join(
        REPO_ROOT, "src", "revit_mcp_server", "extension",
        "RevitMCP.extension", "VERSION",
    )
    with open(path, "r", encoding="utf-8") as f:
        assert f.read().strip() == __version__


def test_manifest_reads_version_file():
    # Parse the manifest module standalone (it imports pyrevit at module level
    # only lazily inside functions... actually `from pyrevit import routes` is
    # top-level there, so exec the version reader in isolation instead).
    import re

    path = os.path.join(
        REPO_ROOT, "src", "revit_mcp_server", "extension",
        "RevitMCP.extension", "revit_mcp", "manifest.py",
    )
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    match = re.search(r"def _read_extension_version.*?return \"0\.0\.0\"", source, re.S)
    assert match, "manifest.py must define _read_extension_version with fallback"
    namespace = {"__file__": path}
    exec(match.group(0), namespace)
    assert namespace["_read_extension_version"]() == __version__


def test_package_version_helper_falls_back():
    from revit_mcp_server.main import _package_version

    assert _package_version()  # never empty
