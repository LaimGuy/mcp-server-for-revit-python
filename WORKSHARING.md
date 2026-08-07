# Worksharing tools (local addition)

Upstream ships `sync_with_central` and save-as-central in `document.py`, but
nothing for worksets or element ownership. These files add that layer:

| File | Runtime | Purpose |
| --- | --- | --- |
| `revit_mcp/worksharing.py` | IronPython 2.7, inside Revit | Routes that call the Revit API |
| `tools/worksharing_tools.py` | CPython 3.13, MCP server process | Tools the model calls |

Registered from the `--- Local additions ---` blocks at the bottom of
`startup.py` and `tools/__init__.py`. Keeping additions in those trailing
blocks is what keeps upstream merges to a trivial "accept both".

## Tools

Read-only:

- `get_worksharing_status` — workshared or not, central vs local vs detached,
  central/local paths, current user, active workset, ownership counts. Warns
  if you have the central model open directly.
- `list_worksets` — every user workset with owner, open/editable/visible
  state, and which one is active.
- `check_element_ownership` — **the important one.** Pre-flight for bulk
  edits: given element ids, a category, or a workset, reports what you can
  edit right now and who is blocking the rest. Run before any bulk operation
  so it does not fail halfway through.

Modifying:

- `set_active_workset` — set the workset new elements land on. Do this
  *before* creating elements, not after.
- `create_workset`
- `move_elements_to_workset` — skips elements owned by others instead of
  failing the whole batch, and reports what it skipped.
- `reload_latest_from_central` — pull others' changes without pushing yours.
- `relinquish_ownership` — unblock teammates without a full sync.

## Notes and limits

- `check_element_ownership` defaults to a 500-element cap. Raise `limit` for
  bigger sweeps, but every element costs a `GetCheckoutStatus` call.
- `list_worksets` deliberately does not count elements per workset — that
  needs a full model iteration. Use `check_element_ownership` with a
  `workset_id` to inspect one workset.
- `relinquish_ownership` only releases items with no unsynchronized changes.
  Anything you actually modified stays checked out until you sync first.
- pyRevit Routes discards query strings, so all options travel in POST
  bodies. Do not add `?flag=true` style parameters — they are silently
  dropped.
- Everything under `revit_mcp/` runs in IronPython 2.7: no f-strings, use
  `.format()`. Everything under `tools/` runs in CPython 3.13.

## Suggested workflow on a shared model

1. `get_worksharing_status` — confirm you are in a local copy, not central.
2. `reload_latest_from_central` — start from current.
3. `check_element_ownership` — confirm the target set is editable.
4. Do the work.
5. `sync_with_central` (upstream tool, in `document_tools.py`).

## Staying current with upstream

```bash
git fetch upstream
git merge upstream/master
```

Conflicts should only ever appear in `startup.py` and `tools/__init__.py`,
and only where both sides appended registrations. Accept both.

Note that pyRevit's own extension "Update" button pulls from `origin` only —
it does not know `upstream` exists, so it will never bring in vendor changes
on its own.
