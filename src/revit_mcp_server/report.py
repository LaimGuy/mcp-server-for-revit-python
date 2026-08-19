# -*- coding: utf-8 -*-
"""`revit-mcp report` — push local telemetry to the team drop folder.

Mirrors the local usage/ and snippets/ JSONL files to
<report_dir>/<username>/{usage,snippets}/. A dumb file copy by design: JSONL
is append-only, each user writes only their own subfolder, and the collector
only reads — so a synced SharePoint/OneDrive folder or a UNC share both work
with no locking story at all. If the folder is unreachable the copy fails
quietly and the next run catches up; the local files remain the source of
truth.

The SQLite db is never copied — it's derived data, rebuilt anywhere by
`revit-mcp ingest`.
"""
import os
import shutil

from . import local_config
from .telemetry_db import data_root


def _username():
    return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"


def run_report(target=None, quiet=False):
    target = target or local_config.report_dir()
    if not target:
        print("No team telemetry folder configured. Set one with:")
        print("  revit-mcp report --to <synced SharePoint folder or UNC path>")
        return 1

    dest_root = os.path.join(target, _username())
    copied = 0
    try:
        for kind in ("usage", "snippets"):
            src_dir = os.path.join(data_root(), kind)
            if not os.path.isdir(src_dir):
                continue
            dst_dir = os.path.join(dest_root, kind)
            os.makedirs(dst_dir, exist_ok=True)
            for name in os.listdir(src_dir):
                if not name.endswith(".jsonl"):
                    continue
                src = os.path.join(src_dir, name)
                dst = os.path.join(dst_dir, name)
                # copy when new or grown (JSONL only ever appends)
                if not os.path.isfile(dst) or os.path.getsize(src) != os.path.getsize(dst):
                    shutil.copy2(src, dst)
                    copied += 1
    except OSError as e:
        print(f"report: could not reach {dest_root} ({e}); will catch up next run")
        return 1

    if not quiet:
        print(f"report: {copied} file(s) refreshed -> {dest_root}")
    return 0
