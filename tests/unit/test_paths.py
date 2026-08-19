# -*- coding: utf-8 -*-
"""Env-independent data-root resolution (the Codex stripped-env bug)."""
import os

import pytest

from revit_mcp_server import paths


def test_env_var_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert paths.local_app_data() == str(tmp_path)
    assert paths.data_root() == os.path.join(str(tmp_path), "revit-mcp")


@pytest.mark.skipif(os.name != "nt", reason="Windows known-folder API")
def test_known_folder_fallback_without_any_env(monkeypatch):
    # The exact Codex scenario: no LOCALAPPDATA, no USERPROFILE, no HOME.
    for var in ("LOCALAPPDATA", "USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH"):
        monkeypatch.delenv(var, raising=False)
    resolved = paths.local_app_data()
    # Windows itself still knows the answer - absolute, never a relative "~"
    assert resolved and os.path.isabs(resolved)
    assert resolved.lower().endswith(os.path.join("appdata", "local"))


def test_userprofile_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(paths, "_known_folder_local_appdata", lambda: None)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert paths.local_app_data() == os.path.join(str(tmp_path), "AppData", "Local")


def test_total_failure_returns_none_not_relative(monkeypatch):
    for var in ("LOCALAPPDATA", "USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(paths, "_known_folder_local_appdata", lambda: None)
    monkeypatch.setattr(os.path, "expanduser", lambda p: "~")
    assert paths.local_app_data() is None
    assert paths.data_root() is None


def test_loggers_skip_quietly_when_unresolvable(monkeypatch):
    from datetime import datetime, timezone

    from revit_mcp_server import snippet_log, usage_log

    monkeypatch.setattr(paths, "local_app_data", lambda: None)
    monkeypatch.setenv("REVIT_MCP_SNIPPET_LOG", "1")
    # must not raise, must not create relative paths
    usage_log.log_usage("t", {}, True, 0.1)
    snippet_log.log_snippet("x", "d", {"output": "y"}, 0.1)
    assert not os.path.exists("~")
