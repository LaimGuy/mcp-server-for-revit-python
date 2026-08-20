# -*- coding: utf-8 -*-
"""SQL Server mirror (sql_push) — tested against a fake pyodbc."""
import sys
import types

import pytest

from revit_mcp_server import sql_push, telemetry_db


class FakeCursor:
    def __init__(self):
        self.executed = []
        self.rowcount = 1

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def execute(self, sql, params=None):
        return self.cursor_obj.execute(sql, params)

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class FakePyodbc(types.ModuleType):
    class Error(Exception):
        pass

    def __init__(self):
        super().__init__("pyodbc")
        self.connections = []
        self.fail_master = False

    def connect(self, conn_str, autocommit=False):
        if self.fail_master and "Database=master" in conn_str:
            raise self.Error("master refused")
        conn = FakeConnection()
        conn.conn_str = conn_str
        conn.autocommit = autocommit
        self.connections.append(conn)
        return conn


@pytest.fixture
def fake_pyodbc(monkeypatch):
    fake = FakePyodbc()
    monkeypatch.setitem(sys.modules, "pyodbc", fake)
    return fake


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """A telemetry.db with one usage row and one snippet row, no team dirs."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    db_path = str(tmp_path / "telemetry.db")
    conn = telemetry_db.connect(db_path)
    conn.execute(
        "INSERT INTO usage VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("u1", "2026-08-20T13:00:00+00:00", "sess", "alice",
         "execute_revit_code", 1, 1, 42, None, "{}"),
    )
    conn.execute(
        "INSERT INTO snippets VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("s1", "not-a-timestamp", "sess", "bob", "abcd1234",
         "x = 1", "test", 1, 1, 10, 5),
    )
    conn.commit()
    conn.close()
    return db_path


def test_push_requires_configured_connection(seeded_db, fake_pyodbc):
    with pytest.raises(RuntimeError, match="No SQL connection"):
        sql_push.push(conn_str=None, db_path=seeded_db)


def test_push_mirrors_both_tables(seeded_db, fake_pyodbc, capsys):
    new_usage, new_snippets = sql_push.push(
        conn_str=sql_push.LOCALDB_CONN, db_path=seeded_db
    )
    assert (new_usage, new_snippets) == (1, 1)
    # master connection created the database, data connection got the rows
    master = fake_pyodbc.connections[0]
    assert "Database=master" in master.conn_str
    assert master.autocommit is True
    assert any("CREATE DATABASE" in sql for sql, _ in master.cursor_obj.executed)
    data = fake_pyodbc.connections[1]
    assert "Database=revit_mcp" in data.conn_str
    assert data.committed
    sqls = [sql for sql, _ in data.cursor_obj.executed]
    assert any("CREATE TABLE dbo.[usage]" in s for s in sqls)
    assert any("CREATE TABLE dbo.snippets" in s for s in sqls)
    inserts = [(s, p) for s, p in data.cursor_obj.executed if p is not None]
    assert all("WHERE NOT EXISTS" in s for s, _ in inserts)
    assert "1 new usage rows" in capsys.readouterr().out


def test_insert_params_carry_antijoin_key_and_parsed_ts(seeded_db, fake_pyodbc):
    sql_push.push(conn_str=sql_push.LOCALDB_CONN, db_path=seeded_db)
    data = fake_pyodbc.connections[1]
    inserts = [p for s, p in data.cursor_obj.executed if p is not None]
    usage_params = next(p for p in inserts if p[0] == "u1")
    assert usage_params[-1] == "u1"  # anti-join key repeated at the end
    assert usage_params[1] is not None  # parsed DATETIMEOFFSET value
    assert usage_params[2] == "2026-08-20T13:00:00+00:00"  # raw preserved
    snip_params = next(p for p in inserts if p[0] == "s1")
    assert snip_params[1] is None  # unparseable ts -> NULL, raw kept
    assert snip_params[2] == "not-a-timestamp"


def test_master_refusal_is_tolerated(seeded_db, fake_pyodbc):
    """Azure-style: no master access, database pre-provisioned."""
    fake_pyodbc.fail_master = True
    new_usage, new_snippets = sql_push.push(
        conn_str=sql_push.LOCALDB_CONN, db_path=seeded_db
    )
    assert (new_usage, new_snippets) == (1, 1)


def test_missing_pyodbc_gives_actionable_error(seeded_db, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyodbc", None)
    with pytest.raises(RuntimeError, match="pyodbc"):
        sql_push.push(conn_str=sql_push.LOCALDB_CONN, db_path=seeded_db)


def test_run_push_sql_saves_localdb_connection(seeded_db, fake_pyodbc):
    from revit_mcp_server import local_config

    args = types.SimpleNamespace(localdb=True, conn=None, db_path=seeded_db)
    assert sql_push.run_push_sql(args) == 0
    assert local_config.load().get("sql_connection") == sql_push.LOCALDB_CONN
