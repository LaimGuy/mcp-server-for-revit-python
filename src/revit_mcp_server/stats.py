# -*- coding: utf-8 -*-
"""`revit-mcp stats` — what the telemetry says, and what's worth promoting.

Auto-ingests the local JSONL logs into the SQLite telemetry db (see
telemetry_db.py — JSONL is the write path, the db is the query path), then
answers from SQL. The promotion-candidate section is the human-facing end of
the learning loop: converged, repeated snippets get a `revit-mcp promote
<hash>` hint. Distinct sources (people/machines) per snippet is the strongest
graduation signal once team dirs are ingested via `revit-mcp ingest --from`.
"""
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import telemetry_db


def _percentile(sorted_values, p):
    if not sorted_values:
        return 0
    idx = min(len(sorted_values) - 1, int(round(p * (len(sorted_values) - 1))))
    return sorted_values[idx]


def _pct(part, whole):
    return "{:.0f}%".format(100.0 * part / whole) if whole else "-"


def run_stats(days=30, db_path=None):
    telemetry_db.ingest(db_path, quiet=True)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(
        timespec="seconds"
    )
    conn = telemetry_db.connect(db_path)
    try:
        print(f"revit-mcp stats - last {days} days")
        print()

        # --- per-tool table ------------------------------------------------
        rows = conn.execute(
            "SELECT tool, ok, route_ok, duration_ms FROM usage WHERE ts >= ?",
            (cutoff,),
        ).fetchall()
        by_tool = defaultdict(list)
        for tool, ok, route_ok, duration in rows:
            by_tool[tool or "?"].append((ok, route_ok, duration or 0))
        if by_tool:
            print(f"{'tool':<32} {'calls':>6} {'ok':>5} {'route_ok':>8} {'p50ms':>7} {'p95ms':>7}")
            print("-" * 70)
            for tool in sorted(by_tool, key=lambda t: -len(by_tool[t])):
                recs = by_tool[tool]
                durations = sorted(r[2] for r in recs)
                ok = sum(1 for r in recs if r[0])
                with_route = [r for r in recs if r[1] is not None]
                route_ok = sum(1 for r in with_route if r[1])
                print("{:<32} {:>6} {:>5} {:>8} {:>7} {:>7}".format(
                    tool[:32], len(recs), _pct(ok, len(recs)),
                    _pct(route_ok, len(with_route)) if with_route else "-",
                    _percentile(durations, 0.50), _percentile(durations, 0.95),
                ))
        else:
            print("No usage records in range.")
        print()

        # --- snippet table -------------------------------------------------
        srows = conn.execute(
            "SELECT hash, ts, session, source, description, route_ok "
            "FROM snippets WHERE ts >= ? ORDER BY ts",
            (cutoff,),
        ).fetchall()
        by_hash = defaultdict(list)
        for rec in srows:
            by_hash[rec[0] or "?"].append(rec)
        if by_hash:
            print(f"{'snippet':<18} {'runs':>5} {'sessions':>8} {'sources':>7} {'last_ok':>7}  last description")
            print("-" * 96)
            for h in sorted(by_hash, key=lambda h: -len(by_hash[h])):
                recs = by_hash[h]
                sessions = len({r[2] for r in recs})
                sources = len({r[3] for r in recs})
                last = recs[-1]
                print("{:<18} {:>5} {:>8} {:>7} {:>7}  {}".format(
                    h, len(recs), sessions, sources,
                    "yes" if last[5] else "no",
                    str(last[4] or "")[:40],
                ))
        else:
            snippets_dir = os.path.join(telemetry_db.data_root(), "snippets")
            if not os.path.isdir(snippets_dir):
                print("Snippet capture is disabled — set REVIT_MCP_SNIPPET_LOG=1 to")
                print("record execute_revit_code snippets for the promotion pipeline.")
            else:
                print("No snippet records in range.")
        print()

        # --- promotion candidates -----------------------------------------
        candidates = []
        for h, recs in by_hash.items():
            last = recs[-1]
            repeated_and_converged = len(recs) >= 3 and last[5]
            converged_in_session = False
            by_session = defaultdict(list)
            for r in recs:
                by_session[r[2]].append(r)
            for sess_recs in by_session.values():
                if len(sess_recs) >= 2 and not sess_recs[0][5] and sess_recs[-1][5]:
                    converged_in_session = True
            if repeated_and_converged or converged_in_session:
                sources = len({r[3] for r in recs})
                candidates.append((h, len(recs), sources, last[4] or ""))
        if candidates:
            print("Promotion candidates:")
            for h, runs, sources, desc in sorted(candidates, key=lambda c: (-c[2], -c[1])):
                src_note = f", {sources} sources" if sources > 1 else ""
                print(f"  {h}  ({runs} runs{src_note})  {str(desc)[:50]}")
                print(f"    -> revit-mcp promote {h}")
        else:
            print("No promotion candidates yet (a candidate = a snippet run 3+ times")
            print("ending in success, or one iterated from failure to success).")
        return 0
    finally:
        conn.close()
