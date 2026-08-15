# -*- coding: utf-8 -*-
"""Tests for the installer's config-surgery helpers."""
from revit_mcp_server.installer import (
    _remove_toml_table,
    _toml_table_present,
    get_ini_value,
    set_ini_value,
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
