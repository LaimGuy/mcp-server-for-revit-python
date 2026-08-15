# -*- coding: utf-8 -*-
"""Snippet capture: opt-in, stable hashing, truthful route outcomes."""
import json
import os

from revit_mcp_server import snippet_log


def test_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("REVIT_MCP_SNIPPET_LOG", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    snippet_log.log_snippet("print(1)", "test", {"output": "1"}, 0.1)
    assert not (tmp_path / "revit-mcp" / "snippets").exists()


def test_enabled_writes_record(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIT_MCP_SNIPPET_LOG", "1")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    snippet_log.log_snippet("print(1)", "count things", {"status": "success", "output": "1"}, 0.25)
    files = list((tmp_path / "revit-mcp" / "snippets").glob("*.jsonl"))
    assert len(files) == 1
    rec = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert rec["v"] == 1
    assert rec["code"] == "print(1)"
    assert rec["description"] == "count things"
    assert rec["route_ok"] is True
    assert rec["duration_ms"] == 250
    assert rec["hash"] == snippet_log.snippet_hash("print(1)")
    assert rec["session"]


def test_hash_stable_across_whitespace():
    a = snippet_log.snippet_hash("x = 1\ny = 2\n")
    b = snippet_log.snippet_hash("x = 1   \n\n\n   \ny = 2")
    c = snippet_log.snippet_hash("x = 1\ny = 3")
    assert a == b
    assert a != c


class TestClassifyRouteResponse:
    def test_output_dict_is_ok(self):
        assert snippet_log.classify_route_response({"status": "success", "output": "hi"})

    def test_error_dict_is_not_ok(self):
        assert not snippet_log.classify_route_response({"error": "boom", "traceback": "..."})

    def test_error_status_is_not_ok(self):
        assert not snippet_log.classify_route_response({"status": "error"})

    def test_error_string_is_not_ok(self):
        assert not snippet_log.classify_route_response("Error: 500 - kaput")

    def test_plain_string_is_ok(self):
        assert snippet_log.classify_route_response("done")

    def test_none_is_not_ok(self):
        assert not snippet_log.classify_route_response(None)
