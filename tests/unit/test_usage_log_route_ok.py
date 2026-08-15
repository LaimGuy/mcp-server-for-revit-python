# -*- coding: utf-8 -*-
"""Additive usage-log fields: route_ok (truthful outcome) and session."""
import json

from revit_mcp_server import usage_log


class TestClassifyResult:
    def test_error_string(self):
        assert usage_log.classify_result("Error: 500 - broke") is False

    def test_error_details_block(self):
        assert usage_log.classify_result("=== ERROR DETAILS ===\nboom") is False

    def test_normal_string(self):
        assert usage_log.classify_result("3 elements selected") is True

    def test_error_dict(self):
        assert usage_log.classify_result({"error": "x"}) is False

    def test_ok_dict(self):
        assert usage_log.classify_result({"count": 3}) is True


def test_record_gains_route_ok_and_session(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("REVIT_MCP_USAGE_LOG", raising=False)
    usage_log.log_usage("some_tool", {"a": 1}, True, 0.05, None, route_ok=False)
    files = list((tmp_path / "revit-mcp" / "usage").glob("*.jsonl"))
    rec = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert rec["v"] == 1  # schema unchanged, fields additive
    assert rec["route_ok"] is False
    assert rec["session"]
    assert rec["args_shape"] == {"a": "int"}
