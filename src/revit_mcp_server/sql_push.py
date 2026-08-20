# -*- coding: utf-8 -*-
"""Mirror the SQLite telemetry db into a SQL Server database.

The pipeline stays layered: JSONL is the write path, SQLite is the local
query path, and this module is the optional third hop — a SQL Server mirror
so telemetry is queryable from a real server (LocalDB for testing, Azure SQL
in the company tenant later; the two differ only by connection string).

The mirror carries EVERY ingested source, not just the local user: ingest
runs first over the local logs and all team-drop person folders, so the SQL
server sees the same multi-user picture `revit-mcp stats` does, with the
`source` column identifying who each row came from.

The connection string lives in %LOCALAPPDATA%/revit-mcp/config.json
(`sql_connection`) — never in this repo. Snippet rows contain real model
code, so the target server must be company-controlled (LocalDB on a company
machine, or a database in the company's own cloud tenant). Do not point this
at a personal or third-party database.

Idempotency mirrors telemetry_db: `line_hash` is the primary key on both
tables and inserts are anti-joined against it, so pushing forever never
duplicates a row and interrupted pushes are safe to rerun.
"""
import re
from datetime import datetime

from . import local_config, telemetry_db

# LocalDB ships with Visual Studio and several Autodesk products, so most
# BIM workstations already have it — a zero-install test target that speaks
# the same T-SQL as Azure SQL.
LOCALDB_CONN = (
    "Driver={ODBC Driver 17 for SQL Server};"
    "Server=(localdb)\\MSSQLLocalDB;"
    "Database=revit_mcp;"
    "Trusted_Connection=yes;"
)

# ts is stored twice on purpose: ts_raw preserves the JSONL string verbatim;
# ts is a parsed DATETIMEOFFSET so date arithmetic works server-side.
TSQL_SCHEMA = [
    """
IF OBJECT_ID('dbo.[usage]', 'U') IS NULL
CREATE TABLE dbo.[usage] (
    line_hash   VARCHAR(24) NOT NULL PRIMARY KEY,
    ts          DATETIMEOFFSET NULL,
    ts_raw      VARCHAR(40),
    session     VARCHAR(64),
    source      NVARCHAR(128),
    tool        NVARCHAR(128),
    ok          BIT,
    route_ok    BIT,
    duration_ms INT,
    error_type  NVARCHAR(128),
    args_shape  NVARCHAR(MAX)
)
""",
    """
IF OBJECT_ID('dbo.snippets', 'U') IS NULL
CREATE TABLE dbo.snippets (
    line_hash    VARCHAR(24) NOT NULL PRIMARY KEY,
    ts           DATETIMEOFFSET NULL,
    ts_raw       VARCHAR(40),
    session      VARCHAR(64),
    source       NVARCHAR(128),
    hash         VARCHAR(16),
    code         NVARCHAR(MAX),
    description  NVARCHAR(MAX),
    ok           BIT,
    route_ok     BIT,
    duration_ms  INT,
    output_chars INT
)
""",
]

_INSERT_USAGE = (
    "INSERT INTO dbo.[usage] (line_hash, ts, ts_raw, session, source, tool,"
    " ok, route_ok, duration_ms, error_type, args_shape)"
    " SELECT ?,?,?,?,?,?,?,?,?,?,?"
    " WHERE NOT EXISTS (SELECT 1 FROM dbo.[usage] WHERE line_hash = ?)"
)

_INSERT_SNIPPETS = (
    "INSERT INTO dbo.snippets (line_hash, ts, ts_raw, session, source, hash,"
    " code, description, ok, route_ok, duration_ms, output_chars)"
    " SELECT ?,?,?,?,?,?,?,?,?,?,?,?"
    " WHERE NOT EXISTS (SELECT 1 FROM dbo.snippets WHERE line_hash = ?)"
)


def _pyodbc():
    try:
        import pyodbc
    except ImportError:
        raise RuntimeError(
            "pyodbc is required for push-sql. Reinstall/update the package "
            "(it is a dependency as of v0.9.0), or `pip install pyodbc`."
        )
    return pyodbc


def _parse_ts(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _database_name(conn_str):
    m = re.search(r"Database=([^;]+)", conn_str, re.IGNORECASE)
    return m.group(1) if m else None


def ensure_database(conn_str):
    """Create the target database if the server allows it (LocalDB/Express).

    On Azure SQL the database is pre-provisioned and master may refuse the
    connection entirely — that's fine, the real connection below will work.
    """
    name = _database_name(conn_str)
    if not name:
        return
    master = re.sub(
        r"Database=[^;]+", "Database=master", conn_str, flags=re.IGNORECASE
    )
    pyodbc = _pyodbc()
    try:
        conn = pyodbc.connect(master, autocommit=True)
        try:
            conn.execute(
                "IF DB_ID(N'{0}') IS NULL CREATE DATABASE [{0}]".format(name)
            )
        finally:
            conn.close()
    except pyodbc.Error:
        pass


def _mirror(cursor, sqlite_conn, table, insert_sql, columns):
    rows = sqlite_conn.execute(
        "SELECT {} FROM {}".format(", ".join(columns), table)
    ).fetchall()
    new = 0
    for row in rows:
        rec = dict(zip(columns, row))
        params = [rec["line_hash"], _parse_ts(rec["ts"]), rec["ts"]]
        params.extend(rec[c] for c in columns if c not in ("line_hash", "ts"))
        params.append(rec["line_hash"])  # the NOT EXISTS anti-join key
        cursor.execute(insert_sql, params)
        new += cursor.rowcount
    return new, len(rows)


def push(conn_str=None, db_path=None, quiet=False):
    """Ingest all telemetry, then mirror the SQLite db to the SQL server.

    Returns (new_usage, new_snippets) row counts actually inserted.
    """
    conn_str = conn_str or local_config.load().get("sql_connection")
    if not conn_str:
        raise RuntimeError(
            "No SQL connection configured. Run "
            "`revit-mcp push-sql --localdb` to target the machine-local "
            "SQL Server LocalDB, or `--conn \"<odbc connection string>\"` "
            "for a real server."
        )

    # Bring SQLite fully up to date first (local logs + every person folder
    # in the team drop), so the mirror always carries all known sources.
    from .stats import _team_dirs

    telemetry_db.ingest(db_path, extra_dirs=_team_dirs(), quiet=True)

    ensure_database(conn_str)
    pyodbc = _pyodbc()
    sqlite_conn = telemetry_db.connect(db_path)
    try:
        server = pyodbc.connect(conn_str)
        try:
            cursor = server.cursor()
            for ddl in TSQL_SCHEMA:
                cursor.execute(ddl)
            new_usage, total_usage = _mirror(
                cursor, sqlite_conn, "usage", _INSERT_USAGE,
                ["line_hash", "ts", "session", "source", "tool", "ok",
                 "route_ok", "duration_ms", "error_type", "args_shape"],
            )
            new_snippets, total_snippets = _mirror(
                cursor, sqlite_conn, "snippets", _INSERT_SNIPPETS,
                ["line_hash", "ts", "session", "source", "hash", "code",
                 "description", "ok", "route_ok", "duration_ms",
                 "output_chars"],
            )
            server.commit()
        finally:
            server.close()
    finally:
        sqlite_conn.close()

    if not quiet:
        print("push-sql: {} new usage rows ({} total), "
              "{} new snippet rows ({} total)".format(
                  new_usage, total_usage, new_snippets, total_snippets))
    return new_usage, new_snippets


def run_push_sql(args):
    """CLI entry for `revit-mcp push-sql`."""
    conn_str = None
    if getattr(args, "localdb", False):
        conn_str = LOCALDB_CONN
    elif getattr(args, "conn", None):
        conn_str = args.conn
    if conn_str:
        local_config.save(sql_connection=conn_str)
        print("SQL connection saved to local config.")
    try:
        push(conn_str, db_path=getattr(args, "db_path", None))
    except RuntimeError as e:
        print(str(e))
        return 1
    return 0
