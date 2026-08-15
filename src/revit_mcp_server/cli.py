# -*- coding: utf-8 -*-
"""Console entry point: `revit-mcp [serve|install|doctor|uninstall]`.

No subcommand means `serve`, so an MCP client config needs nothing beyond the
executable itself.
"""
import argparse
import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    parser = argparse.ArgumentParser(
        prog="revit-mcp",
        description="MCP server for Autodesk Revit via pyRevit Routes.",
    )
    sub = parser.add_subparsers(dest="cmd")

    serve = sub.add_parser("serve", help="Run the MCP server (default; stdio transport)")
    serve.add_argument("--sse", action="store_true")
    serve.add_argument("--http", "--streamable-http", action="store_true", dest="http")
    serve.add_argument("--combined", action="store_true")

    install = sub.add_parser("install", help="Set up the pyRevit extension and MCP client configs")
    install.add_argument("--yes", action="store_true", help="Answer yes to all prompts")
    install.add_argument(
        "--client",
        choices=["claude", "codex", "both", "none"],
        default="both",
        help="Which MCP client configs to wire (default: both)",
    )

    sub.add_parser("doctor", help="Diagnose the install end to end")

    sub.add_parser("update", help="Re-copy the extension and refresh configs to this package version")

    stats = sub.add_parser("stats", help="Usage and snippet telemetry, with promotion candidates")
    stats.add_argument("--days", type=int, default=30)

    ingest = sub.add_parser("ingest", help="Load JSONL telemetry into the SQLite db (idempotent)")
    ingest.add_argument("--from", dest="extra_dirs", action="append", default=[],
                        metavar="DIR", help="Extra telemetry dir to merge (repeatable), e.g. a coworker's copied revit-mcp folder")
    ingest.add_argument("--db", dest="db_path", help="Database path override")

    promote = sub.add_parser("promote", help="Scaffold a named tool from a captured snippet")
    promote.add_argument("target", nargs="?", help="Snippet hash from `revit-mcp stats`")
    promote.add_argument("--from-file", dest="from_file", help="Seed the spec from a .py snippet file")
    promote.add_argument("--apply", dest="apply_spec", help="Generate artifacts from a promotion spec JSON")
    promote.add_argument("--force", action="store_true", help="Overwrite existing generated files")

    uninstall = sub.add_parser("uninstall", help="Remove the pyRevit extension and client config")
    uninstall.add_argument("--yes", action="store_true", help="Answer yes to all prompts")

    args = parser.parse_args(argv)

    if args.cmd == "install":
        from .installer import run_install
        return run_install(args)
    if args.cmd == "doctor":
        from .doctor import run_doctor
        return run_doctor()
    if args.cmd == "update":
        from .installer import run_update
        return run_update(args)
    if args.cmd == "stats":
        from .stats import run_stats
        return run_stats(days=args.days)
    if args.cmd == "ingest":
        from .telemetry_db import ingest
        ingest(args.db_path, args.extra_dirs)
        return 0
    if args.cmd == "promote":
        from .promote import run_promote
        return run_promote(args)
    if args.cmd == "uninstall":
        from .installer import run_uninstall
        return run_uninstall(args)

    # serve (explicit or default). Reconstruct the transport flags main.py expects.
    serve_argv = []
    if args.cmd == "serve":
        if args.sse:
            serve_argv.append("--sse")
        if args.http:
            serve_argv.append("--http")
        if args.combined:
            serve_argv.append("--combined")
    from .main import run_server
    run_server(serve_argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
