# Contracts

These are the interfaces later phases (auto tool-building, C# graduation)
depend on. They are locked as of v0.2.0. Breaking any of them requires a major
version bump and a deliberate migration plan.

## Tool naming

- `snake_case`, verb-first: `get_`, `list_`, `create_`, `set_`, `check_`,
  `execute_`, `place_`, `launch_`.
- A tool name shipped in a tagged release is **permanent**. Renaming means
  adding a new tool and deprecating the old one in its docstring — never
  removing it within a major version.
- Names describe intent, not implementation. `get_selected_elements` stays
  `get_selected_elements` whether it is served by an IronPython route or a C#
  add-in.

## Manifest (v1)

`GET /revit_mcp/tools/` returns:

```json
{
  "manifest_version": 1,
  "server": {"name": "RevitMCP", "extension_version": "0.2.0"},
  "tools": [
    {
      "name": "get_revit_status",
      "origin": "builtin",
      "routes": ["GET /status/"],
      "description": "..."
    }
  ]
}
```

- `origin` is one of `"builtin" | "generated" | "graduated"`.
- Schema changes are **additive only**; anything breaking bumps
  `manifest_version`.
- Maintained by hand in `revit_mcp/manifest.py` (step 5 of the add-a-tool
  recipe in `LLM.txt`).

## Graduation invariant

When a tool is reimplemented — LLM-generated snippet → hardcoded IronPython
route → compiled C# add-in — its **name, argument names, and result shape do
not change**. Only the manifest `origin` field changes. An MCP client must not
be able to tell the difference. This is what lets popular tools graduate to a
developer team without breaking anyone's workflow.

## Usage log (v1)

One JSON line per MCP tool call, written to
`%LOCALAPPDATA%\revit-mcp\usage\usage-YYYYMM.jsonl`:

```json
{"v": 1, "ts": "2026-08-15T14:00:00+00:00", "tool": "execute_revit_code",
 "args_shape": {"code": "str", "description": "str"}, "ok": true,
 "duration_ms": 840}
```

- `args_shape` records **type names only** — never values, paths, or model
  data.
- Opt out with `REVIT_MCP_USAGE_LOG=0`.
- Logging failures are swallowed; telemetry must never break a tool call.
- This file is the input for future usage aggregation and the graduation
  pipeline. Additive schema changes only; `v` bumps on breaking changes.

## Snippet log (v1) — opt-in

Unlike the usage log, this sink stores **actual code and descriptions** passed
to `execute_revit_code`. It is therefore **opt-in**: `REVIT_MCP_SNIPPET_LOG=1`.
One JSON line per call to `%LOCALAPPDATA%\revit-mcp\snippets\snippets-YYYYMM.jsonl`:

```json
{"v": 1, "ts": "...", "session": "a1b2c3d4e5f6", "hash": "9f2c4e1a8b7d3f05",
 "code": "...", "description": "...", "ok": true, "route_ok": true,
 "duration_ms": 840, "output_chars": 212}
```

- `hash` = sha256 of whitespace-normalized code, first 16 hex chars — stable
  across whitespace-only retries so retried logic clusters under one key.
- `route_ok` is the truthful outcome (route errors come back as strings, not
  exceptions, so exception-based `ok` alone is insufficient).
- Additive-only; `v` bumps on breaking changes. Never merged into the usage
  log — that file's types-only rule is permanent.

## Usage log — additive v1 fields (added in 0.5.0)

- `route_ok`: outcome derived from the tool's return value (heuristic: error
  strings/blocks and error dicts are failures). A legitimate output starting
  with "Error:" logs a false negative; accepted, affects stats ranking only.
- `session`: per-server-process id; lets analysis detect fail→fail→success
  convergence within one client session.

## Promotion spec (v1)

Input to `revit-mcp promote --apply`. One spec generates BOTH halves of a tool
(route + MCP wrapper) plus registrations, manifest entry, and a smoke test —
single-sourcing the parameter list so the halves cannot drift.

```json
{"spec_version": 1, "name": "count_duct_fittings", "description": "...",
 "params": [{"name": "level", "type": "str", "default": null,
             "required": false, "doc": "..."}],
 "route": {"method": "POST", "path": "/count_duct_fittings/"},
 "mutates_model": false, "body_py2": "...", "result_keys": ["count"],
 "source_hash": "9f2c4e1a8b7d3f05"}
```

Validation refuses: non-verb-first names, manifest/module collisions, bare
`DB.Transaction` in mutating bodies (must use `safe_tx`), py3-only syntax in
`body_py2`. Generated tools carry `origin: "generated"` and follow the same
naming permanence once tagged.

## Telemetry database (derived, v1)

`%LOCALAPPDATA%\revit-mcp\telemetry.db` (SQLite) is the **query path**; the
JSONL files remain the only write path and the source of truth. The server
never touches the db. `revit-mcp ingest` loads JSONL into it idempotently
(rows keyed by a hash of source + raw line — re-ingesting never duplicates),
and `revit-mcp stats` auto-ingests local dirs before querying. Deleting the
db loses nothing a re-ingest can't rebuild.

Each row carries a `source` label: the local username for local ingests, the
directory basename for `ingest --from <dir>` merges. Distinct sources per
snippet hash is the cross-user graduation signal. Team aggregation = copy
coworkers' `%LOCALAPPDATA%\revit-mcp` folders (or just their `snippets/` and
`usage/` subdirs) to any location and point `--from` at them — no server or
schema changes involved.

Schema changes are additive; `meta.db_version` bumps on breaking changes.

SQL Server mirror (added in 0.9.0): `revit-mcp push-sql` mirrors the SQLite
db to a SQL Server (`dbo.[usage]` / `dbo.snippets`, same columns plus a
parsed `ts` DATETIMEOFFSET alongside `ts_raw`; `line_hash` stays the primary
key, inserts anti-join against it so pushes are idempotent). The mirror is a
third derived hop — JSONL remains the only write path. The ODBC connection
string is per-machine config (`sql_connection` in config.json), never a repo
constant, and the target server must be company-controlled because snippet
rows contain model code.

Team drop layout (v1): `<team folder>/<username>/{usage,snippets}/*.jsonl`,
written only by `revit-mcp report` on each user's machine (mirror copy, each
user owns exactly their folder). The team folder path is per-machine config
(`%LOCALAPPDATA%\revit-mcp\config.json`), never a constant in this repo —
internal paths stay out of public source. The SQLite db is never placed on
the share.

## Generated-code fences

Machine-managed regions are delimited by `# >>> revit-mcp:generated*:begin/end`
markers in `startup.py`, `tools/__init__.py`, and `manifest.py`. Only
`revit-mcp promote` edits between markers (atomic writes, idempotent); manual
edits belong outside. Each generated registration is individually try/except-
isolated: a broken generated module logs an error and is skipped, never taking
builtin routes or tools down with it.

## Connection

- Base URL: `http://127.0.0.1:48884/revit_mcp/` (second Revit instance:
  48885, and so on through 48887).
- `REVIT_HOST` / `REVIT_PORT` env vars override; otherwise the server probes
  the range and validates the `/revit_mcp/status/` path shape before trusting
  a port.
