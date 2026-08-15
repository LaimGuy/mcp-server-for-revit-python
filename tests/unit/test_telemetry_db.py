# -*- coding: utf-8 -*-
"""SQLite telemetry: idempotent ingest, source stamping, --from merging."""
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from revit_mcp_server import telemetry_db

NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")

USAGE_REC = {"v": 1, "ts": NOW, "session": "s1", "tool": "get_revit_status",
             "ok": True, "route_ok": True, "duration_ms": 5, "args_shape": {}}
SNIPPET_REC = {"v": 1, "ts": NOW, "session": "s1", "hash": "abc123",
               "code": "x = 1", "description": "test", "ok": True,
               "route_ok": True, "duration_ms": 9, "output_chars": 3}


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


@pytest.fixture
def local_data(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("USERNAME", "lstevenson")
    root = tmp_path / "revit-mcp"
    _write_jsonl(root / "usage" / "usage-202608.jsonl", [USAGE_REC])
    _write_jsonl(root / "snippets" / "snippets-202608.jsonl", [SNIPPET_REC])
    return root


def test_ingest_loads_both_kinds(local_data):
    totals = telemetry_db.ingest(quiet=True)
    assert totals["new"] == 2
    conn = sqlite3.connect(str(local_data / "telemetry.db"))
    assert conn.execute("SELECT count(*) FROM usage").fetchone()[0] == 1
    assert conn.execute("SELECT source FROM usage").fetchone()[0] == "lstevenson"
    assert conn.execute("SELECT hash, code FROM snippets").fetchone() == ("abc123", "x = 1")
    conn.close()


def test_reingest_is_idempotent(local_data):
    telemetry_db.ingest(quiet=True)
    totals = telemetry_db.ingest(quiet=True)
    assert totals["new"] == 0
    assert totals["seen"] == 2
    conn = sqlite3.connect(str(local_data / "telemetry.db"))
    assert conn.execute("SELECT count(*) FROM snippets").fetchone()[0] == 1
    conn.close()


def test_extra_dir_with_subdirs_gets_own_source(local_data, tmp_path):
    coworker = tmp_path / "jsmith"
    _write_jsonl(coworker / "snippets" / "snippets-202608.jsonl",
                 [dict(SNIPPET_REC, session="s9")])
    telemetry_db.ingest(extra_dirs=[str(coworker)], quiet=True)
    conn = sqlite3.connect(str(local_data / "telemetry.db"))
    sources = {r[0] for r in conn.execute("SELECT source FROM snippets")}
    assert sources == {"lstevenson", "jsmith"}
    # same snippet hash across two sources — the graduation signal
    assert conn.execute(
        "SELECT count(DISTINCT source) FROM snippets WHERE hash='abc123'"
    ).fetchone()[0] == 2
    conn.close()


def test_flat_extra_dir_routes_by_filename_prefix(local_data, tmp_path):
    flat = tmp_path / "flatdrop"
    _write_jsonl(flat / "usage-202608.jsonl", [dict(USAGE_REC, session="s7")])
    _write_jsonl(flat / "snippets-202608.jsonl", [dict(SNIPPET_REC, session="s7")])
    telemetry_db.ingest(extra_dirs=[str(flat)], quiet=True)
    conn = sqlite3.connect(str(local_data / "telemetry.db"))
    # each line landed in exactly its own table (no cross-contamination)
    assert conn.execute("SELECT count(*) FROM usage").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM snippets").fetchone()[0] == 2
    assert conn.execute(
        "SELECT count(*) FROM usage WHERE tool IS NULL").fetchone()[0] == 0
    conn.close()


def test_corrupt_lines_skipped(local_data):
    path = local_data / "usage" / "usage-202608.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write('{"broken\n')
        f.write("[1, 2]\n")  # valid JSON, not a record dict
    totals = telemetry_db.ingest(quiet=True)
    assert totals["new"] == 2  # the two good records only


def test_db_is_derived_and_rebuildable(local_data):
    telemetry_db.ingest(quiet=True)
    (local_data / "telemetry.db").unlink()
    totals = telemetry_db.ingest(quiet=True)
    assert totals["new"] == 2
