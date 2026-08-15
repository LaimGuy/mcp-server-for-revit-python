# -*- coding: utf-8 -*-
"""Stats aggregation and promotion-candidate detection."""
import json
from datetime import datetime, timezone

import pytest

from revit_mcp_server import stats


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path / "revit-mcp"


def test_stats_runs_and_finds_candidate(data_root, capsys):
    _write_jsonl(data_root / "usage" / "usage-x.jsonl", [
        {"v": 1, "ts": NOW, "tool": "get_revit_status", "ok": True,
         "route_ok": True, "duration_ms": 5, "args_shape": {}},
        {"v": 1, "ts": NOW, "tool": "get_revit_status", "ok": True,
         "route_ok": False, "duration_ms": 9, "args_shape": {}},
    ])
    _write_jsonl(data_root / "snippets" / "snippets-x.jsonl", [
        {"v": 1, "ts": NOW, "session": "s1", "hash": "abc123", "code": "x",
         "description": "count fittings", "route_ok": True, "duration_ms": 10},
        {"v": 1, "ts": NOW, "session": "s1", "hash": "abc123", "code": "x",
         "description": "count fittings", "route_ok": True, "duration_ms": 11},
        {"v": 1, "ts": NOW, "session": "s2", "hash": "abc123", "code": "x",
         "description": "count fittings", "route_ok": True, "duration_ms": 12},
    ])
    assert stats.run_stats(days=1) == 0
    out = capsys.readouterr().out
    assert "get_revit_status" in out
    assert "abc123" in out
    assert "revit-mcp promote abc123" in out


def test_convergence_candidate_fail_then_success(data_root, capsys):
    _write_jsonl(data_root / "snippets" / "snippets-x.jsonl", [
        {"v": 1, "ts": NOW, "session": "s1", "hash": "conv01", "code": "x",
         "description": "iterating", "route_ok": False, "duration_ms": 5},
        {"v": 1, "ts": NOW, "session": "s1", "hash": "conv01", "code": "x",
         "description": "iterating", "route_ok": True, "duration_ms": 5},
    ])
    stats.run_stats(days=1)
    out = capsys.readouterr().out
    assert "revit-mcp promote conv01" in out


def test_corrupt_lines_skipped(data_root, capsys):
    path = data_root / "usage" / "usage-x.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"broken\n' + json.dumps(
        {"v": 1, "ts": NOW, "tool": "t", "ok": True, "duration_ms": 1,
         "args_shape": {}}) + "\n", encoding="utf-8")
    assert stats.run_stats(days=1) == 0
    assert "t" in capsys.readouterr().out


def test_capture_disabled_hint(data_root, capsys):
    stats.run_stats(days=1)
    assert "REVIT_MCP_SNIPPET_LOG=1" in capsys.readouterr().out
