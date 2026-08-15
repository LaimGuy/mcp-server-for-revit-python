# -*- coding: utf-8 -*-
"""SQLite telemetry store — the query path of the learning loop.

The JSONL files stay the WRITE path (append-only, lock-free, crash-safe; the
server never touches this db). `revit-mcp ingest` loads them into
%LOCALAPPDATA%/revit-mcp/telemetry.db, idempotently: every line is keyed by a
hash of (source, raw line), so re-ingesting the same files forever never
duplicates a row. The db is derived data — deleting it loses nothing that a
re-ingest can't rebuild.

`source` is the identity of the machine/user a line came from: the local
username for local ingests, a directory label for --from dirs. That makes
"how many distinct people converged on this snippet" — the strongest
graduation signal — a GROUP BY away, and makes the future team pipeline a
matter of pointing --from at a network share.
"""
import hashlib
import json
import os
import sqlite3

DB_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS usage (
    line_hash TEXT PRIMARY KEY,
    ts TEXT,
    session TEXT,
    source TEXT,
    tool TEXT,
    ok INTEGER,
    route_ok INTEGER,
    duration_ms INTEGER,
    error_type TEXT,
    args_shape TEXT
);
CREATE INDEX IF NOT EXISTS idx_usage_tool ON usage(tool);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage(ts);
CREATE TABLE IF NOT EXISTS snippets (
    line_hash TEXT PRIMARY KEY,
    ts TEXT,
    session TEXT,
    source TEXT,
    hash TEXT,
    code TEXT,
    description TEXT,
    ok INTEGER,
    route_ok INTEGER,
    duration_ms INTEGER,
    output_chars INTEGER
);
CREATE INDEX IF NOT EXISTS idx_snippets_hash ON snippets(hash);
CREATE INDEX IF NOT EXISTS idx_snippets_ts ON snippets(ts);
"""


def data_root():
    return os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "revit-mcp"
    )


def default_db_path():
    return os.path.join(data_root(), "telemetry.db")


def connect(path=None):
    path = path or default_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES ('db_version', ?)",
        (str(DB_VERSION),),
    )
    conn.commit()
    return conn


def _line_hash(source, raw_line):
    return hashlib.sha256(
        (source + "\n" + raw_line).encode("utf-8")
    ).hexdigest()[:24]


def _to_int(value):
    if value is None:
        return None
    return 1 if value else 0


def _ingest_line(conn, kind, source, raw_line):
    """Insert one JSONL line. Returns True if it was new."""
    try:
        rec = json.loads(raw_line)
    except ValueError:
        return False
    if not isinstance(rec, dict) or "ts" not in rec:
        return False
    key = _line_hash(source, raw_line)
    if kind == "usage":
        cur = conn.execute(
            "INSERT OR IGNORE INTO usage VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                key,
                rec.get("ts"),
                rec.get("session"),
                source,
                rec.get("tool"),
                _to_int(rec.get("ok")),
                _to_int(rec.get("route_ok")) if "route_ok" in rec else None,
                rec.get("duration_ms"),
                rec.get("error_type"),
                json.dumps(rec.get("args_shape", {})),
            ),
        )
    else:
        cur = conn.execute(
            "INSERT OR IGNORE INTO snippets VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                key,
                rec.get("ts"),
                rec.get("session"),
                source,
                rec.get("hash"),
                rec.get("code"),
                rec.get("description"),
                _to_int(rec.get("ok")),
                _to_int(rec.get("route_ok")) if "route_ok" in rec else None,
                rec.get("duration_ms"),
                rec.get("output_chars"),
            ),
        )
    return cur.rowcount > 0


def ingest_dir(conn, directory, source, kind, prefix=None):
    """Ingest .jsonl files in directory (optionally only prefix-matching ones).

    Returns (new_rows, seen_lines).
    """
    new, seen = 0, 0
    if not os.path.isdir(directory):
        return new, seen
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".jsonl"):
            continue
        if prefix and not name.startswith(prefix):
            continue
        try:
            with open(os.path.join(directory, name), "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    seen += 1
                    if _ingest_line(conn, kind, source, line):
                        new += 1
        except OSError:
            continue
    conn.commit()
    return new, seen


def _local_source():
    return os.environ.get("USERNAME") or os.environ.get("USER") or "local"


def ingest(db_path=None, extra_dirs=None, quiet=False):
    """Ingest local JSONL dirs (+ optional extra dirs) into the db.

    An extra dir may contain usage-*.jsonl and/or snippets-*.jsonl files
    directly, or usage/ and snippets/ subdirectories (the layout of a copied
    %LOCALAPPDATA%/revit-mcp). Its source label is the directory's basename.
    """
    conn = connect(db_path)
    try:
        totals = {"new": 0, "seen": 0}

        def _run(directory, source, kind, prefix=None):
            new, seen = ingest_dir(conn, directory, source, kind, prefix)
            totals["new"] += new
            totals["seen"] += seen

        local = _local_source()
        _run(os.path.join(data_root(), "usage"), local, "usage")
        _run(os.path.join(data_root(), "snippets"), local, "snippets")

        for extra in extra_dirs or []:
            label = os.path.basename(os.path.normpath(extra)) or extra
            for kind in ("usage", "snippets"):
                sub = os.path.join(extra, kind)
                if os.path.isdir(sub):
                    _run(sub, label, kind)
                else:
                    # flat dir: rely on the usage-*/snippets-* filename
                    # convention so lines land in the right table
                    _run(extra, label, kind, prefix=kind)

        if not quiet:
            print("ingest: {} new rows ({} lines scanned) -> {}".format(
                totals["new"], totals["seen"], db_path or default_db_path()))
        return totals
    finally:
        conn.close()
