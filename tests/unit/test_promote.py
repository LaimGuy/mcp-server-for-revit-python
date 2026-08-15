# -*- coding: utf-8 -*-
"""Promotion scaffolder: validation, generation, fence handling."""
import ast
import json
import os
import shutil

import pytest

from revit_mcp_server import promote

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


GOOD_SPEC = {
    "spec_version": 1,
    "name": "count_duct_fittings",
    "description": "Count duct fittings, optionally filtered by level name.",
    "params": [
        {"name": "level", "type": "str", "default": None, "required": False,
         "doc": "Level name filter; all levels when omitted"},
    ],
    "route": {"method": "POST", "path": "/count_duct_fittings/"},
    "mutates_model": False,
    "body_py2": (
        "fittings = list(model_elements(doc, DB.BuiltInCategory.OST_DuctFitting))\n"
        "if level:\n"
        "    fittings = [f for f in fittings if safe_name(doc.GetElement(f.LevelId)) == level]\n"
        "result = {'count': len(fittings), 'message': '{} duct fittings'.format(len(fittings))}"
    ),
    "result_keys": ["count", "message"],
    "source_hash": "abc123",
}


@pytest.fixture
def repo_copy(tmp_path):
    """Minimal copy of the fenced files so promote can edit them safely."""
    root = tmp_path / "repo"
    pkg = root / "src" / "revit_mcp_server"
    ext = pkg / "extension" / "RevitMCP.extension"
    for rel in (
        "src/revit_mcp_server/extension/RevitMCP.extension/startup.py",
        "src/revit_mcp_server/extension/RevitMCP.extension/revit_mcp/manifest.py",
        "src/revit_mcp_server/tools/__init__.py",
    ):
        src = os.path.join(REPO_ROOT, *rel.split("/"))
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    (pkg / "tools" / "utils.py").write_text("", encoding="utf-8")
    return root


def _paths(root):
    return promote._paths(str(root))


class TestValidation:
    def test_good_spec_passes(self, repo_copy):
        errors, _, _ = promote._validate_spec(GOOD_SPEC, _paths(repo_copy), force=False)
        assert errors == []

    def test_bad_verb_rejected(self, repo_copy):
        spec = dict(GOOD_SPEC, name="ducts_count")
        errors, _, _ = promote._validate_spec(spec, _paths(repo_copy), force=False)
        assert any("verb-first" in e for e in errors)

    def test_manifest_collision_rejected(self, repo_copy):
        spec = dict(GOOD_SPEC, name="get_revit_status", route={"method": "POST", "path": "/status2/"})
        errors, _, _ = promote._validate_spec(spec, _paths(repo_copy), force=False)
        assert any("already exists" in e for e in errors)

    def test_bare_transaction_rejected(self, repo_copy):
        spec = dict(GOOD_SPEC, mutates_model=True,
                    body_py2="t = DB.Transaction(doc, 'x')\nresult = {}")
        errors, _, _ = promote._validate_spec(spec, _paths(repo_copy), force=False)
        assert any("safe_tx" in e for e in errors)

    def test_fstring_body_rejected(self, repo_copy):
        spec = dict(GOOD_SPEC, body_py2="result = {'m': f'{doc}'}")
        errors, _, _ = promote._validate_spec(spec, _paths(repo_copy), force=False)
        assert any("f-string" in e for e in errors)

    def test_todo_params_rejected(self, repo_copy):
        spec = dict(GOOD_SPEC, params=[{"name": "TODO_param", "type": "str",
                                        "default": None, "required": False, "doc": "TODO"}])
        errors, _, _ = promote._validate_spec(spec, _paths(repo_copy), force=False)
        assert any("TODO" in e for e in errors)


class TestApply:
    def _apply(self, repo_copy, tmp_path, spec=GOOD_SPEC):
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        return promote._apply(str(spec_path), _paths(repo_copy), force=False)

    def test_generates_all_artifacts(self, repo_copy, tmp_path):
        assert self._apply(repo_copy, tmp_path) == 0
        pkg = repo_copy / "src" / "revit_mcp_server"
        route = pkg / "extension" / "RevitMCP.extension" / "revit_mcp" / "gen_count_duct_fittings.py"
        tool = pkg / "tools" / "gen_count_duct_fittings_tools.py"
        assert route.is_file() and tool.is_file()

        # Generated route is py2-clean and syntactically valid
        assert promote._py2_violations(route.read_text(encoding="utf-8"), "r") == []
        ast.parse(tool.read_text(encoding="utf-8"))

        startup = (pkg / "extension" / "RevitMCP.extension" / "startup.py").read_text(encoding="utf-8")
        assert "from revit_mcp.gen_count_duct_fittings import" in startup
        tools_init = (pkg / "tools" / "__init__.py").read_text(encoding="utf-8")
        assert "GENERATED_TOOLS.add('count_duct_fittings')" in tools_init
        manifest = (pkg / "extension" / "RevitMCP.extension" / "revit_mcp" / "manifest.py").read_text(encoding="utf-8")
        assert "'count_duct_fittings'" in manifest and '"generated"' in manifest

    def test_apply_twice_is_idempotent(self, repo_copy, tmp_path):
        assert self._apply(repo_copy, tmp_path) == 0
        spec = dict(GOOD_SPEC)
        spec_path = tmp_path / "spec2.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        assert promote._apply(str(spec_path), _paths(repo_copy), force=True) == 0
        startup = (repo_copy / "src" / "revit_mcp_server" / "extension" /
                   "RevitMCP.extension" / "startup.py").read_text(encoding="utf-8")
        assert startup.count("from revit_mcp.gen_count_duct_fittings import") == 1

    def test_validation_failure_writes_nothing(self, repo_copy, tmp_path):
        bad = dict(GOOD_SPEC, name="bad name!")
        assert self._apply(repo_copy, tmp_path, bad) == 1
        pkg = repo_copy / "src" / "revit_mcp_server"
        assert not list((pkg / "tools").glob("gen_*"))


def test_generated_tools_survive_trim(monkeypatch):
    from revit_mcp_server import tools as tools_pkg

    class FakeManager:
        def __init__(self, names):
            self._tools = {n: object() for n in names}

        def remove_tool(self, name):
            del self._tools[name]

    class FakeServer:
        def __init__(self, names):
            self._tool_manager = FakeManager(names)

    monkeypatch.delenv("REVIT_MCP_ALL_TOOLS", raising=False)
    monkeypatch.setattr(tools_pkg, "GENERATED_TOOLS", {"count_duct_fittings"})
    server = FakeServer(["execute_revit_code", "count_duct_fittings", "some_other_tool"])
    tools_pkg._trim_tool_surface(server)
    kept = set(server._tool_manager._tools)
    assert "count_duct_fittings" in kept
    assert "some_other_tool" not in kept
