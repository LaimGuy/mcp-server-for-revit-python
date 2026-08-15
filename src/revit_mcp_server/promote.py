# -*- coding: utf-8 -*-
"""`revit-mcp promote` — turn a proven snippet into a named tool.

Deterministic scaffolder; no LLM calls. It runs inside a Claude Code (or any)
session: the model or human does the intelligent part — extracting parameters
from the snippet — by editing the promotion spec. Two steps:

  revit-mcp promote <hash>              # seed promotions/<name>.json from the
                                        # snippet sink (or --from-file x.py)
  revit-mcp promote --apply <spec.json> # generate all six artifacts

Both halves of the tool (IronPython route + MCP wrapper) are emitted from the
ONE spec, so their parameter lists cannot drift apart. Machine edits land only
between `>>> revit-mcp:generated:*` markers, atomically.

Promote runs against a source checkout of this repo — an installed uvx copy
has no fences to edit.
"""
import ast
import json
import os
import py_compile
import re
import tempfile

NAME_RE = re.compile(
    r"^(get|list|create|set|check|execute|place|launch|count|tag|update|delete)"
    r"_[a-z][a-z0-9_]*$"
)
PARAM_TYPES = {"str": "str", "int": "int", "float": "float", "bool": "bool", "list": "list"}
SPEC_VERSION = 1

_MARK = "revit-mcp:generated"


def _repo_root():
    # src/revit_mcp_server/promote.py -> repo root two levels up from package
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    startup = os.path.join(here, "extension", "RevitMCP.extension", "startup.py")
    if not os.path.isfile(startup):
        return None
    with open(startup, "r", encoding="utf-8") as f:
        if _MARK + ":begin" not in f.read():
            return None
    return root


def _paths(root):
    pkg = os.path.join(root, "src", "revit_mcp_server")
    ext = os.path.join(pkg, "extension", "RevitMCP.extension")
    return {
        "pkg": pkg,
        "ext": ext,
        "startup": os.path.join(ext, "startup.py"),
        "manifest": os.path.join(ext, "revit_mcp", "manifest.py"),
        "tools_init": os.path.join(pkg, "tools", "__init__.py"),
        "route_dir": os.path.join(ext, "revit_mcp"),
        "tools_dir": os.path.join(pkg, "tools"),
        "promotions": os.path.join(root, "promotions"),
        "gen_tests": os.path.join(root, "tests", "unit", "generated"),
    }


# --- step 1: seed a spec ----------------------------------------------------

def _latest_snippet(target_hash):
    root = os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
        "revit-mcp", "snippets",
    )
    latest = None
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            if not name.endswith(".jsonl"):
                continue
            with open(os.path.join(root, name), "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("hash") == target_hash:
                        latest = rec
    return latest


def _suggest_name(description):
    words = re.findall(r"[a-z0-9]+", (description or "").lower())[:5]
    slug = "_".join(words) or "new_tool"
    if not NAME_RE.match(slug):
        slug = "TODO_verb_" + slug
    return slug


def _seed_spec(code, description, source_hash, paths):
    name = _suggest_name(description)
    spec = {
        "spec_version": SPEC_VERSION,
        "name": name,
        "description": description or "TODO: one-line description",
        "params": [
            {
                "name": "TODO_param",
                "type": "str",
                "default": None,
                "required": False,
                "doc": "TODO: describe, or delete this entry if the tool takes no params",
            }
        ],
        "route": {"method": "POST", "path": "/{}/".format(name.replace("TODO_verb_", ""))},
        "mutates_model": "TODO true if the code changes the model",
        "body_py2": code,
        "result_keys": ["message"],
        "source_hash": source_hash,
    }
    os.makedirs(paths["promotions"], exist_ok=True)
    out = os.path.join(paths["promotions"], "{}.json".format(name))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)
    print("Spec written: {}".format(os.path.relpath(out)))
    print()
    print("Next steps:")
    print("  1. Edit the spec: fix name (verb-first snake_case), params,")
    print("     mutates_model, and adapt body_py2 to use the params and end by")
    print("     assigning a dict to `result`.")
    print("  2. revit-mcp promote --apply {}".format(os.path.relpath(out)))
    return 0


# --- step 2: validate + generate -------------------------------------------

FORBIDDEN_PY2 = {
    ast.JoinedStr: "f-string",
    ast.AnnAssign: "variable annotation",
    ast.NamedExpr: "walrus operator",
    ast.Match: "match statement",
    ast.AsyncFunctionDef: "async def",
    ast.Await: "await",
    ast.YieldFrom: "yield from",
}


def _py2_violations(source, label):
    problems = []
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return ["{}: syntax error: {}".format(label, e)]
    for node in ast.walk(tree):
        for node_type, what in FORBIDDEN_PY2.items():
            if isinstance(node, node_type):
                problems.append("{}:{} {}".format(label, node.lineno, what))
        if isinstance(node, ast.arg) and node.annotation is not None:
            problems.append("{}:{} argument annotation".format(label, node.lineno))
    return problems


def _validate_spec(spec, paths, force):
    errors = []
    if spec.get("spec_version") != SPEC_VERSION:
        errors.append("spec_version must be {}".format(SPEC_VERSION))
    name = spec.get("name", "")
    if not NAME_RE.match(name):
        errors.append(
            "name {!r} must be verb-first snake_case ({})".format(
                name, NAME_RE.pattern
            )
        )
    if not isinstance(spec.get("mutates_model"), bool):
        errors.append("mutates_model must be true or false (resolve the TODO)")
    body = spec.get("body_py2", "")
    if not body.strip():
        errors.append("body_py2 is empty")
    if "TODO" in json.dumps(spec.get("params", [])):
        errors.append("params still contain TODO placeholders")
    for p in spec.get("params", []):
        if not re.match(r"^[a-z][a-z0-9_]*$", p.get("name", "")):
            errors.append("param name {!r} invalid".format(p.get("name")))
        if p.get("type") not in PARAM_TYPES:
            errors.append("param {} type must be one of {}".format(
                p.get("name"), sorted(PARAM_TYPES)))
    method = spec.get("route", {}).get("method")
    if method not in ("GET", "POST"):
        errors.append("route.method must be GET or POST")
    if method == "GET" and spec.get("params"):
        errors.append("GET routes cannot carry params; use POST")
    path = spec.get("route", {}).get("path", "")
    if not re.match(r"^/[a-z0-9_]+/$", path):
        errors.append("route.path must look like /snake_case/")

    if spec.get("mutates_model") is True and "DB.Transaction(" in body:
        errors.append(
            "body_py2 uses a bare DB.Transaction — use safe_tx(doc, name) "
            "(a modal warning would hang the bridge)"
        )
    errors.extend(_py2_violations(body, "body_py2"))

    # Name collisions: manifest (static parse — Revit may be closed) + files
    with open(paths["manifest"], "r", encoding="utf-8") as f:
        manifest_src = f.read()
    if '"name": "{}"'.format(name) in manifest_src:
        errors.append("tool name {!r} already exists in the manifest".format(name))
    route_file = os.path.join(paths["route_dir"], "gen_{}.py".format(name))
    tool_file = os.path.join(paths["tools_dir"], "gen_{}_tools.py".format(name))
    if not force:
        for f_ in (route_file, tool_file):
            if os.path.exists(f_):
                errors.append("{} exists (use --force to overwrite)".format(
                    os.path.relpath(f_)))
    return errors, route_file, tool_file


_PY_DEFAULTS = {"str": "None", "int": "0", "float": "0.0", "bool": "False", "list": "None"}


def _py_literal(value):
    return repr(value) if value is not None else "None"


def _route_module(spec):
    name = spec["name"]
    params = spec["params"]
    method = spec["route"]["method"]
    lines = [
        "# -*- coding: UTF-8 -*-",
        "# GENERATED by revit-mcp promote - spec: promotions/{}.json".format(name),
        '"""{}"""'.format(spec["description"].replace('"', "'")),
        "import json",
        "import logging",
        "import traceback",
        "",
        "logger = logging.getLogger(__name__)",
        "",
        "",
        "def register_{}_routes(api):".format(name),
        "    from pyrevit import routes",
        "",
    ]
    handler_args = "doc, request" if method == "POST" else "doc"
    lines += [
        "    @api.route('{}', methods=[\"{}\"])".format(spec["route"]["path"], method),
        "    def {}_handler({}):".format(name, handler_args),
        "        try:",
    ]
    if method == "POST":
        lines += [
            "            data = {}",
            "            if request and getattr(request, 'data', None):",
            "                data = json.loads(request.data) if isinstance(request.data, str) else request.data",
        ]
        for p in params:
            lines.append("            {} = data.get({!r}, {})".format(
                p["name"], p["name"], _py_literal(p.get("default"))))
    call_args = ", ".join(["doc"] + [p["name"] for p in params])
    lines += [
        "            result = _run_{}({})".format(name, call_args),
        "            return routes.make_response(data=result)",
        "        except Exception as e:",
        "            logger.error('{} failed: {{}}'.format(str(e)))".format(name),
        "            return routes.make_response(",
        "                data={'error': str(e), 'traceback': traceback.format_exc()},",
        "                status=500,",
        "            )",
        "",
        "    logger.info('{} routes registered')".format(name),
        "",
        "",
        "def _run_{}({}):".format(name, ", ".join(["doc"] + [p["name"] for p in params])),
        "    from pyrevit import revit, DB",
        "    from revit_mcp.utils import safe_tx, safe_name, family_name, model_elements",
    ]
    for body_line in spec["body_py2"].splitlines():
        lines.append("    " + body_line if body_line.strip() else "")
    lines += [
        "    return result",
        "",
    ]
    return "\n".join(lines)


def _tool_module(spec):
    name = spec["name"]
    params = spec["params"]
    method = spec["route"]["method"]
    sig_parts = []
    for p in sorted(params, key=lambda p: not p.get("required")):
        if p.get("required"):
            sig_parts.append("{}: {}".format(p["name"], PARAM_TYPES[p["type"]]))
        else:
            default = p.get("default")
            sig_parts.append("{}: {} = {}".format(
                p["name"], PARAM_TYPES[p["type"]], _py_literal(default)))
    sig_parts.append("ctx: Context = None")
    doc_args = "\n".join(
        "            {}: {}".format(p["name"], p.get("doc", "")) for p in params
    )
    lines = [
        "# -*- coding: utf-8 -*-",
        "# GENERATED by revit-mcp promote - spec: promotions/{}.json".format(name),
        '"""Generated tool: {}"""'.format(name),
        "",
        "from mcp.server.mcpserver import Context",
        "from .utils import format_response",
        "",
        "",
        "def register_{}_tools(mcp, revit_get, revit_post, revit_image=None):".format(name),
        "    _ = revit_image",
        "",
        "    @mcp.tool()",
        "    async def {}({}) -> str:".format(name, ", ".join(sig_parts)),
        '        """{}'.format(spec["description"]),
    ]
    if params:
        lines += ["", "        Args:", doc_args]
    lines += ['        """']
    if method == "POST":
        lines += ["        payload = {}"]
        for p in params:
            lines.append("        if {} is not None:".format(p["name"]))
            lines.append("            payload[{!r}] = {}".format(p["name"], p["name"]))
        lines.append(
            "        response = await revit_post({!r}, payload, ctx, timeout=60.0)".format(
                spec["route"]["path"]))
    else:
        lines.append(
            "        response = await revit_get({!r}, ctx)".format(spec["route"]["path"]))
    lines += [
        "        return format_response(response)",
        "",
    ]
    return "\n".join(lines)


def _test_module(spec):
    name = spec["name"]
    params = spec["params"]
    method = spec["route"]["method"]
    call_kwargs = ", ".join(
        ["{}={}".format(p["name"], _py_literal(p.get("default")) if not p.get("required")
                        else {"str": "'x'", "int": "1", "float": "1.0", "bool": "True", "list": "[]"}[p["type"]])
         for p in params] + ["ctx=None"])
    mock = "mock_revit_post" if method == "POST" else "mock_revit_get"
    lines = [
        "# -*- coding: utf-8 -*-",
        "# GENERATED by revit-mcp promote - spec: promotions/{}.json".format(name),
        "import pytest",
        "",
        "from revit_mcp_server.tools.gen_{}_tools import register_{}_tools".format(name, name),
        "",
        "",
        "class TestGenerated_{}:".format(name),
        "    @pytest.fixture(autouse=True)",
        "    def setup(self, mock_mcp, mock_revit_get, mock_revit_post):",
        "        mock_revit_get.return_value = {'status': 'success', 'message': 'OK'}",
        "        mock_revit_post.return_value = {'status': 'success', 'message': 'OK'}",
        "        register_{}_tools(mock_mcp, mock_revit_get, mock_revit_post)".format(name),
        "        self.tools = mock_mcp.tools",
        "        self.mock = {}".format(mock),
        "",
        "    async def test_registers_and_hits_route(self):",
        "        assert {!r} in self.tools".format(name),
        "        await self.tools[{!r}]({})".format(name, call_kwargs),
        "        args = self.mock.call_args[0]",
        "        assert args[0] == {!r}".format(spec["route"]["path"]),
        "",
    ]
    return "\n".join(lines)


def _atomic_write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _insert_in_fence(path, marker_ns, entry_lines, dedupe_key):
    """Insert lines before the fence's end marker. Idempotent by dedupe_key."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    begin = "# >>> {}:begin".format(marker_ns)
    end = "# >>> {}:end".format(marker_ns)
    if content.count(begin) != 1 or content.count(end) != 1:
        raise RuntimeError(
            "{}: fence markers {} missing or duplicated".format(path, marker_ns))
    if dedupe_key in content:
        return False  # already applied
    head, rest = content.split(begin, 1)
    mid, tail = rest.split(end, 1)
    # match the indentation of the end marker line
    indent = ""
    for line in content.splitlines():
        if line.strip() == end.strip():
            indent = line[: len(line) - len(line.lstrip())]
            break
    block = "\n".join(indent + l if l.strip() else "" for l in entry_lines)
    # mid ends with newline + the end-marker's own indentation; drop those
    # trailing spaces or the block's first line gets double-indented.
    new = head + begin + mid.rstrip(" ") + block + "\n" + indent + end.strip() + tail
    _atomic_write(path, new)
    return True


def _apply(spec_path, paths, force):
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = json.load(f)
    errors, route_file, tool_file = _validate_spec(spec, paths, force)
    if errors:
        print("Spec validation failed:")
        for e in errors:
            print("  - " + e)
        return 1

    name = spec["name"]
    route_src = _route_module(spec)
    tool_src = _tool_module(spec)
    test_src = _test_module(spec)

    # Self-check the generated code BEFORE writing anything
    problems = _py2_violations(route_src, "generated route")
    if problems:
        print("Generated route failed the IronPython 2.7 check (bug in spec body?):")
        for p in problems:
            print("  - " + p)
        return 1

    _atomic_write(route_file, route_src)
    _atomic_write(tool_file, tool_src)
    test_file = os.path.join(paths["gen_tests"], "test_gen_{}.py".format(name))
    init_file = os.path.join(paths["gen_tests"], "__init__.py")
    if not os.path.exists(init_file):
        _atomic_write(init_file, "")
    _atomic_write(test_file, test_src)
    for f_ in (route_file, tool_file, test_file):
        py_compile.compile(f_, doraise=True)

    # Registration fences
    _insert_in_fence(
        paths["startup"], _MARK,
        [
            "try:",
            "    from revit_mcp.gen_{} import register_{}_routes".format(name, name),
            "    register_{}_routes(api)".format(name),
            "except Exception as _gen_e:",
            "    logger.error(\"generated route '{}' failed to register: %s\", _gen_e)".format(name),
        ],
        "revit_mcp.gen_{}".format(name),
    )
    _insert_in_fence(
        paths["tools_init"], _MARK,
        [
            "try:",
            "    from .gen_{}_tools import register_{}_tools".format(name, name),
            "    register_{}_tools(mcp_server, revit_get_func, revit_post_func)".format(name),
            "except Exception as _gen_e:",
            "    logger.error(\"generated tool '{}' failed to register: %s\", _gen_e)".format(name),
        ],
        ".gen_{}_tools".format(name),
    )
    _insert_in_fence(
        paths["tools_init"], "revit-mcp:generated-tools",
        ["GENERATED_TOOLS.add({!r})".format(name)],
        "GENERATED_TOOLS.add({!r})".format(name),
    )
    _insert_in_fence(
        paths["manifest"], "revit-mcp:generated-manifest",
        [
            "MANIFEST[\"tools\"].append({",
            "    \"name\": {!r},".format(name),
            "    \"origin\": \"generated\",",
            "    \"routes\": [{!r}],".format(
                "{} {}".format(spec["route"]["method"], spec["route"]["path"])),
            "    \"description\": {!r},".format(spec["description"]),
            "})",
        ],
        "\"name\": {!r},".format(name),
    )

    print("Generated tool '{}':".format(name))
    for f_ in (route_file, tool_file, test_file):
        print("  " + os.path.relpath(f_))
    print("  + registrations in startup.py, tools/__init__.py, manifest.py")
    print()
    print("Next: run `uv run pytest tests/unit tests/test_extension_py2_guard.py`,")
    print("then `revit-mcp update` and restart Revit.")
    return 0


def run_promote(args):
    root = _repo_root()
    if root is None:
        print("promote needs a source checkout of the repo (with generated-code")
        print("fences); an installed copy is read-only. Clone the repo and run")
        print("`uv run revit-mcp promote ...` from it.")
        return 1
    paths = _paths(root)

    if args.apply_spec:
        return _apply(args.apply_spec, paths, args.force)
    if args.from_file:
        with open(args.from_file, "r", encoding="utf-8") as f:
            code = f.read()
        from .snippet_log import snippet_hash
        return _seed_spec(code, os.path.basename(args.from_file), snippet_hash(code), paths)
    if args.target:
        rec = _latest_snippet(args.target)
        if rec is None:
            print("No snippet with hash {} in the sink. Run `revit-mcp stats`".format(args.target))
            print("to list captured hashes (capture: REVIT_MCP_SNIPPET_LOG=1).")
            return 1
        return _seed_spec(rec["code"], rec.get("description", ""), args.target, paths)
    print("usage: revit-mcp promote <hash> | --from-file x.py | --apply spec.json")
    return 1
