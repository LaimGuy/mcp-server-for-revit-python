# -*- coding: utf-8 -*-
"""Tests for the installer's config-surgery helpers."""
import os

import pytest

from revit_mcp_server import installer
from revit_mcp_server.installer import (
    _codex_revit_has_env,
    _codex_toml_snippet,
    _remove_toml_table,
    _toml_table_present,
    get_ini_value,
    set_ini_value,
    wire_codex,
)

CODEX_CONFIG = """\
[windows]
sandbox = "elevated"

[mcp_servers.revitmcp]
command = "py"
args = ["-3.13", "C:\\\\old\\\\main.py"]

[mcp_servers.revitmcp.tools.execute_revit_code]
approval_mode = "approve"

[mcp_servers.revitmcp.tools.get_revit_status]
approval_mode = "approve"

[mcp_servers.navisworksmcp]
command = "node"
""".splitlines()


class TestRemoveTomlTable:
    def test_removes_base_and_subtables(self):
        out = _remove_toml_table(list(CODEX_CONFIG), "mcp_servers.revitmcp")
        joined = "\n".join(out)
        assert "revitmcp" not in joined
        # neighbours untouched
        assert "[windows]" in joined
        assert "[mcp_servers.navisworksmcp]" in joined
        assert 'command = "node"' in joined

    def test_removes_orphaned_subtables_without_base(self):
        # The exact bug: base table already gone, sub-tables left behind
        # implicitly recreate the server with no transport.
        orphaned = [l for l in CODEX_CONFIG
                    if l.strip() not in ('[mcp_servers.revitmcp]',
                                         'command = "py"',
                                         'args = ["-3.13", "C:\\\\old\\\\main.py"]')]
        assert _toml_table_present(orphaned, "mcp_servers.revitmcp")
        out = _remove_toml_table(orphaned, "mcp_servers.revitmcp")
        assert "revitmcp" not in "\n".join(out)

    def test_does_not_remove_prefix_lookalikes(self):
        lines = ["[mcp_servers.revit]", 'command = "uvx"']
        out = _remove_toml_table(lines, "mcp_servers.revitmcp")
        assert out == lines


class TestTomlTablePresent:
    def test_detects_base(self):
        assert _toml_table_present(CODEX_CONFIG, "mcp_servers.revitmcp")

    def test_detects_subtable_only(self):
        assert _toml_table_present(
            ["[mcp_servers.revitmcp.tools.x]"], "mcp_servers.revitmcp")

    def test_absent(self):
        assert not _toml_table_present(CODEX_CONFIG, "mcp_servers.revit")


class TestIniSurgery:
    def test_set_existing_key(self):
        lines = ["[routes]", "enabled = false", "", "[core]", "x = 1"]
        lines, changed = set_ini_value(lines, "routes", "enabled", "true")
        assert changed
        assert get_ini_value(lines, "routes", "enabled") == "true"
        assert get_ini_value(lines, "core", "x") == "1"

    def test_append_missing_section(self):
        lines, changed = set_ini_value(["[core]", "x = 1"], "routes", "enabled", "true")
        assert changed
        assert get_ini_value(lines, "routes", "enabled") == "true"

    def test_noop_when_already_set(self):
        lines = ["[routes]", "enabled = true"]
        _, changed = set_ini_value(lines, "routes", "enabled", "true")
        assert not changed


class TestCaptureWiring:
    def test_snippet_includes_env_when_capture(self):
        assert "REVIT_MCP_SNIPPET_LOG" in _codex_toml_snippet(capture=True)
        assert "REVIT_MCP_SNIPPET_LOG" not in _codex_toml_snippet(capture=False)

    def test_env_detection(self):
        lines = ["[mcp_servers.revit]", 'command = "uvx"',
                 'env = { "REVIT_MCP_SNIPPET_LOG" = "1" }']
        assert _codex_revit_has_env(lines)
        assert not _codex_revit_has_env(lines[:2])

    def test_wire_codex_inserts_env_preserving_subtables(self, tmp_path, monkeypatch):
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        cfg = tmp_path / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text(
            "[mcp_servers.revit]\n"
            'command = "uvx"\n'
            'args = ["--from", "x", "revit-mcp"]\n'
            "\n"
            "[mcp_servers.revit.tools.execute_revit_code]\n"
            'approval_mode = "approve"\n',
            encoding="utf-8",
        )
        wire_codex(assume_yes=True, capture=True)
        text = cfg.read_text(encoding="utf-8")
        assert '"REVIT_MCP_SNIPPET_LOG" = "1"' in text
        # Codex passes servers ONLY the listed env; LOCALAPPDATA must ride along
        assert '"LOCALAPPDATA"' in text
        # the user's per-tool approval survived (a full replace would drop it)
        assert "[mcp_servers.revit.tools.execute_revit_code]" in text
        # env landed inside the base table, before the sub-table
        assert text.index("REVIT_MCP_SNIPPET_LOG") < text.index("revit.tools")

    def test_wire_codex_upgrades_stale_env_line(self, tmp_path, monkeypatch):
        # A pre-0.7.1 env line (capture only, no LOCALAPPDATA) gets replaced
        # in place, preserving everything else.
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        cfg = tmp_path / ".codex" / "config.toml"
        cfg.parent.mkdir()
        cfg.write_text(
            "[mcp_servers.revit]\n"
            'command = "uvx"\n'
            'args = ["--from", "x", "revit-mcp"]\n'
            'env = { "REVIT_MCP_SNIPPET_LOG" = "1" }\n',
            encoding="utf-8",
        )
        wire_codex(assume_yes=True, capture=True)
        text = cfg.read_text(encoding="utf-8")
        assert text.count("env =") == 1
        assert '"LOCALAPPDATA"' in text

    def test_wire_codex_idempotent_when_env_current(self, tmp_path, monkeypatch):
        from revit_mcp_server.installer import _codex_env_line

        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        cfg = tmp_path / ".codex" / "config.toml"
        cfg.parent.mkdir()
        original = (
            "[mcp_servers.revit]\n"
            'command = "uvx"\n'
            'args = ["--from", "x", "revit-mcp"]\n'
            + _codex_env_line(True) + "\n"
        )
        cfg.write_text(original, encoding="utf-8")
        wire_codex(assume_yes=True, capture=True)
        assert cfg.read_text(encoding="utf-8") == original
