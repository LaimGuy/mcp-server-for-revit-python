# -*- coding: utf-8 -*-
"""Tripwire for the IronPython 2.7 constraint.

Everything under src/revit_mcp_server/extension/ executes inside Revit on
IronPython 2.7. Python-3-only syntax there doesn't fail loudly — the module
just fails to import at Revit startup and its routes silently vanish. This
test catches the common offenders at CI time instead.

The code must stay in the py2/py3 common subset (it already is — ast.parse
under CPython 3 requires that much).
"""
import ast
import os

import pytest

EXTENSION_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src", "revit_mcp_server", "extension",
)


def _extension_sources():
    for root, dirs, files in os.walk(EXTENSION_ROOT):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


FORBIDDEN = {
    ast.JoinedStr: "f-string",
    ast.AnnAssign: "variable annotation",
    ast.NamedExpr: "walrus operator",
    ast.Match: "match statement",
    ast.AsyncFunctionDef: "async def",
    ast.Await: "await",
    ast.YieldFrom: "yield from",
}
# Note: ast.Starred is NOT forbidden wholesale — f(*args) is fine in py2;
# only starred assignment targets (a, *b = x) are py3-only, checked below.


def _violations(path):
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    found = []
    for node in ast.walk(tree):
        for node_type, label in FORBIDDEN.items():
            if isinstance(node, node_type):
                found.append("{}:{} {}".format(path, node.lineno, label))
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, (ast.Tuple, ast.List)) and any(
                    isinstance(el, ast.Starred) for el in target.elts
                ):
                    found.append("{}:{} starred assignment".format(path, node.lineno))
        if isinstance(node, ast.arguments) and (node.kwonlyargs or node.posonlyargs):
            found.append("{}: keyword/positional-only args".format(path))
        if isinstance(node, (ast.FunctionDef, ast.Lambda)) and getattr(node, "returns", None):
            found.append("{}:{} return annotation".format(path, node.lineno))
        if isinstance(node, ast.arg) and node.annotation is not None:
            found.append("{}:{} argument annotation".format(path, node.lineno))
    return found


@pytest.mark.parametrize("path", sorted(_extension_sources()), ids=os.path.basename)
def test_extension_module_is_ironpython27_safe(path):
    problems = _violations(path)
    assert not problems, "IronPython 2.7 cannot load:\n" + "\n".join(problems)
