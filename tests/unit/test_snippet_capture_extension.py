# -*- coding: utf-8 -*-
"""Revit-side snippet capture (extension module, loaded standalone)."""
import importlib.util
import json
import os

import pytest

MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "src", "revit_mcp_server", "extension", "RevitMCP.extension",
    "revit_mcp", "snippet_capture.py",
)


@pytest.fixture
def capture_mod():
    spec = importlib.util.spec_from_file_location("snippet_capture_ext", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def _enable(tmp_path):
    root = tmp_path / "revit-mcp"
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.json").write_text(
        json.dumps({"snippet_capture": True}), encoding="utf-8")


def test_disabled_without_config(capture_mod, local):
    assert capture_mod.is_enabled() is False
    assert capture_mod.capture("x=1", "d", "s", True, 10, 5) is False
    assert not (local / "revit-mcp" / "snippets").exists()


def test_capture_writes_v1_record(capture_mod, local):
    _enable(local)
    assert capture_mod.capture("x = 1", "count things", "sess12", True, 42.9, 7) is True
    files = list((local / "revit-mcp" / "snippets").glob("*.jsonl"))
    rec = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert rec["v"] == 1
    assert rec["session"] == "sess12"
    assert rec["route_ok"] is True
    assert rec["duration_ms"] == 42
    assert rec["output_chars"] == 7
    assert rec["code"] == "x = 1"


def test_hash_matches_server_side(capture_mod, local):
    from revit_mcp_server.snippet_log import snippet_hash as server_hash

    code = "a = 1   \n\n\n  \nb = 2"
    assert capture_mod.snippet_hash(code) == server_hash(code)


def test_failure_recorded_with_route_ok_false(capture_mod, local):
    _enable(local)
    capture_mod.capture("boom", "d", None, False, 5, 0)
    files = list((local / "revit-mcp" / "snippets").glob("*.jsonl"))
    rec = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert rec["route_ok"] is False
    assert rec["session"] == "revit"  # default when server passed none


def test_config_toggle_without_restart(capture_mod, local):
    _enable(local)
    assert capture_mod.is_enabled() is True
    (local / "revit-mcp" / "config.json").write_text(
        json.dumps({"snippet_capture": False}), encoding="utf-8")
    assert capture_mod.is_enabled() is False  # re-read per call
