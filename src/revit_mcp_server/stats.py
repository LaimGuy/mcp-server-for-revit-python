# -*- coding: utf-8 -*-
"""`revit-mcp stats` — what the telemetry says, and what's worth promoting.

Reads the usage log (always-on, types only) and the snippet log (opt-in,
holds code) and prints plain-text tables. The promotion-candidate section is
the human-facing end of the learning loop: converged, repeated snippets get a
`revit-mcp promote <hash>` hint.
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone


def _data_root():
    return os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "revit-mcp"
    )


def _read_jsonl(directory, since):
    records = []
    if not os.path.isdir(directory):
        return records
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".jsonl"):
            continue
        try:
            with open(os.path.join(directory, name), "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue  # corrupt/partial line
                    ts = rec.get("ts", "")
                    try:
                        when = datetime.fromisoformat(ts)
                    except ValueError:
                        continue
                    if when >= since:
                        records.append(rec)
        except OSError:
            continue
    return records


def _percentile(sorted_values, p):
    if not sorted_values:
        return 0
    idx = min(len(sorted_values) - 1, int(round(p * (len(sorted_values) - 1))))
    return sorted_values[idx]


def _pct(part, whole):
    return "{:.0f}%".format(100.0 * part / whole) if whole else "-"


def run_stats(days=30):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    usage = _read_jsonl(os.path.join(_data_root(), "usage"), since)
    snippets = _read_jsonl(os.path.join(_data_root(), "snippets"), since)

    print(f"revit-mcp stats - last {days} days")
    print()

    # --- per-tool table ----------------------------------------------------
    by_tool = defaultdict(list)
    for rec in usage:
        by_tool[rec.get("tool", "?")].append(rec)
    if by_tool:
        print(f"{'tool':<32} {'calls':>6} {'ok':>5} {'route_ok':>8} {'p50ms':>7} {'p95ms':>7}")
        print("-" * 70)
        for tool in sorted(by_tool, key=lambda t: -len(by_tool[t])):
            recs = by_tool[tool]
            durations = sorted(r.get("duration_ms", 0) for r in recs)
            ok = sum(1 for r in recs if r.get("ok"))
            with_route = [r for r in recs if "route_ok" in r]
            route_ok = sum(1 for r in with_route if r.get("route_ok"))
            print("{:<32} {:>6} {:>5} {:>8} {:>7} {:>7}".format(
                tool[:32], len(recs), _pct(ok, len(recs)),
                _pct(route_ok, len(with_route)) if with_route else "-",
                _percentile(durations, 0.50), _percentile(durations, 0.95),
            ))
    else:
        print("No usage records in range.")
    print()

    # --- snippet table -----------------------------------------------------
    by_hash = defaultdict(list)
    for rec in snippets:
        by_hash[rec.get("hash", "?")].append(rec)
    if by_hash:
        print(f"{'snippet':<18} {'runs':>5} {'sessions':>8} {'last_ok':>7}  last description")
        print("-" * 90)
        for h in sorted(by_hash, key=lambda h: -len(by_hash[h])):
            recs = sorted(by_hash[h], key=lambda r: r.get("ts", ""))
            sessions = len({r.get("session") for r in recs})
            last = recs[-1]
            print("{:<18} {:>5} {:>8} {:>7}  {}".format(
                h, len(recs), sessions,
                "yes" if last.get("route_ok") else "no",
                str(last.get("description", ""))[:45],
            ))
    else:
        snippets_dir = os.path.join(_data_root(), "snippets")
        if not os.path.isdir(snippets_dir):
            print("Snippet capture is disabled — set REVIT_MCP_SNIPPET_LOG=1 to")
            print("record execute_revit_code snippets for the promotion pipeline.")
        else:
            print("No snippet records in range.")
    print()

    # --- promotion candidates ---------------------------------------------
    candidates = []
    for h, recs in by_hash.items():
        recs = sorted(recs, key=lambda r: r.get("ts", ""))
        last = recs[-1]
        repeated_and_converged = len(recs) >= 3 and last.get("route_ok")
        # fail -> ... -> success inside one session = iterated to convergence
        converged_in_session = False
        by_session = defaultdict(list)
        for r in recs:
            by_session[r.get("session")].append(r)
        for sess_recs in by_session.values():
            if len(sess_recs) >= 2 and not sess_recs[0].get("route_ok") and sess_recs[-1].get("route_ok"):
                converged_in_session = True
        if repeated_and_converged or converged_in_session:
            candidates.append((h, len(recs), last.get("description", "")))
    if candidates:
        print("Promotion candidates:")
        for h, runs, desc in candidates:
            print(f"  {h}  ({runs} runs)  {str(desc)[:50]}")
            print(f"    -> revit-mcp promote {h}")
    else:
        print("No promotion candidates yet (a candidate = a snippet run 3+ times")
        print("ending in success, or one iterated from failure to success).")
    return 0
