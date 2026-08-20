# revit-mcp

MCP server for Autodesk Revit, built on [pyRevit Routes](https://pyrevitlabs.notion.site/Routes-1cbb2fd6dc8443bb9df0e1fa1e2b6d94).
Lets Claude Code, Claude Desktop, or Codex read and modify a live Revit model —
query status and views, run IronPython against the open document, place
families, check clashes and worksharing ownership, and more.

Forked from
[mcp-servers-for-revit/mcp-server-for-revit-python](https://github.com/mcp-servers-for-revit/mcp-server-for-revit-python)
and repackaged as an installable Python package with a one-command setup.

## Install

Requirements: Windows, Revit 2021+, [pyRevit](https://pyrevitlabs.io/) installed.

1. Install [uv](https://docs.astral.sh/uv/) (once), then open a **new** terminal:

   ```powershell
   powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

2. Run the installer. It sets up the pyRevit extension, enables the Routes
   server, and registers the MCP server with Claude Code and/or Codex:

   ```powershell
   uvx --from https://github.com/LaimGuy/mcp-server-for-revit-python/archive/refs/heads/master.zip revit-mcp install
   ```

3. Restart Revit.

4. Verify — all green means you're done:

   ```powershell
   uvx --from https://github.com/LaimGuy/mcp-server-for-revit-python/archive/refs/heads/master.zip revit-mcp doctor
   ```

5. In Claude Code, ask: *"What's the current Revit status?"*

No cloning, no JSON editing, no absolute paths. To remove everything:
`... revit-mcp uninstall`.

## Updating

```powershell
uvx --refresh --from https://github.com/LaimGuy/mcp-server-for-revit-python/archive/refs/heads/master.zip revit-mcp update
```

Then restart Revit if the output says the extension changed. (`--refresh`
makes uvx re-download the latest build; without it, uvx serves its cached
copy.)

## How it works

Two halves, one package:

- **`RevitMCP.extension`** (IronPython 2.7, runs inside Revit) — a pyRevit
  extension that registers HTTP routes under
  `http://127.0.0.1:48884/revit_mcp/`. Installed into
  `%APPDATA%\pyRevit\Extensions` by `revit-mcp install`.
- **MCP server** (Python 3.11+, launched by your MCP client over stdio) —
  translates MCP tool calls into HTTP requests to those routes. Started as
  `uvx --from <this repo> revit-mcp`.

pyRevit Routes serves the first Revit instance on port 48884, the second on
48885, and so on. The server probes the range automatically; set `REVIT_PORT`
to pin one, `REVIT_HOST` for a non-local bridge.

## Tools

By default the MCP surface is trimmed to 7 core tools (large tool lists make
MCP clients defer schemas; `execute_revit_code` reaches everything anyway):

| Tool | Purpose |
|---|---|
| `execute_revit_code` | Run IronPython against the open model — the workhorse |
| `get_revit_status` | Bridge liveness and document state |
| `get_revit_model_info` | Document identity and element counts |
| `get_current_view_info` | Active view context |
| `list_revit_views` | View lookup by name |
| `get_selected_elements` | The user's current selection |
| `check_element_ownership` | Worksharing pre-flight before a bulk edit |

Set `REVIT_MCP_ALL_TOOLS=1` to register the full ~60-tool surface (views,
families, MEP creation, clash detection, worksharing, documentation, ...).

A running Revit also serves `GET /revit_mcp/tools/` — a versioned manifest of
the tool ecosystem. See [docs/CONTRACTS.md](docs/CONTRACTS.md) for the naming,
manifest, and telemetry contracts.

## Usage telemetry (local only)

The server appends one JSON line per tool call to
`%LOCALAPPDATA%\revit-mcp\usage\` — tool name, argument *types*, success, and
duration. No values, paths, or model data are recorded, and nothing leaves the
machine. This feeds future tooling that identifies which tools are worth
promoting to hardcoded implementations. Opt out with `REVIT_MCP_USAGE_LOG=0`.

## Team telemetry (optional)

With snippet capture on, `revit-mcp report` copies each machine's local
telemetry to `<team folder>\<username>\` — point it at a synced
SharePoint/OneDrive folder or UNC share with `revit-mcp report --to <path>`
(the installer also offers this, plus a daily scheduled task). The collector
machine runs `revit-mcp stats` and sees candidates ranked by how many people
converged on the same snippet. Data never leaves company storage; the SQLite
db is derived locally and never shared.

## SQL Server mirror (optional)

`revit-mcp push-sql` mirrors the telemetry database — every ingested source,
not just the local user — to a SQL Server, so the team picture is queryable
with real T-SQL. `--localdb` targets the machine-local SQL Server LocalDB
(ships with Visual Studio and many Autodesk products; ideal for testing);
`--conn "<odbc string>"` targets a real server such as an Azure SQL database
in the company tenant — the code is identical, only the connection string
changes. The connection string is remembered in the machine-local config,
never in this repo, and once set the daily report task keeps the server
current automatically. The target must be company-controlled: snippet rows
contain real model code.

## Manual client configuration

`revit-mcp install` does this for you; for reference:

Claude Code:

```
claude mcp add revit -s user -- uvx --from https://github.com/LaimGuy/mcp-server-for-revit-python/archive/refs/heads/master.zip revit-mcp
```

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.revit]
command = "uvx"
args = ["--from", "https://github.com/LaimGuy/mcp-server-for-revit-python/archive/refs/heads/master.zip", "revit-mcp"]
```

HTTP transports (`revit-mcp serve --sse | --http | --combined`) are available
for clients that can't spawn a stdio process; the combined server listens on
`127.0.0.1:8000` (`REVIT_MCP_HTTP_PORT` overrides).

## Development

```powershell
git clone https://github.com/LaimGuy/mcp-server-for-revit-python
cd mcp-server-for-revit-python
uv sync --extra test
uv run pytest tests/unit tests/test_extension_py2_guard.py   # offline
uv run revit-mcp install --client none                        # local dev install
uv run pytest -m integration                                  # needs a running Revit
```

Layout: `src/revit_mcp_server/` is the CPython MCP server;
`src/revit_mcp_server/extension/RevitMCP.extension/` is the IronPython payload
copied verbatim at install time. Everything under `extension/` must stay
IronPython 2.7-compatible — `tests/test_extension_py2_guard.py` enforces the
obvious offenders. `LLM.txt` documents the route API and the add-a-tool
recipe.

## Security note

pyRevit Routes has no authentication, and `execute_revit_code` is arbitrary
code execution inside Revit. The bridge binds to localhost; do not expose the
port beyond the machine.

## License

See [LICENSE](LICENSE). Upstream credit: Juan D. Rodriguez / Jean-Marc
Couffin and contributors.
