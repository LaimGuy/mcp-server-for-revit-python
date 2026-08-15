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

## Connection

- Base URL: `http://127.0.0.1:48884/revit_mcp/` (second Revit instance:
  48885, and so on through 48887).
- `REVIT_HOST` / `REVIT_PORT` env vars override; otherwise the server probes
  the range and validates the `/revit_mcp/status/` path shape before trusting
  a port.
