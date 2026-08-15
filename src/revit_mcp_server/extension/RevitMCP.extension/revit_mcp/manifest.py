# -*- coding: UTF-8 -*-
"""Tool manifest endpoint — contract v1.

Serves GET /revit_mcp/tools/ so any client (doctor, future tool-builder,
graduation tooling) can ask a running Revit what this server offers without
guessing. Rules, per docs/CONTRACTS.md:

- manifest_version bumps only on breaking changes; additions are free.
- Tool names are snake_case, verb-first, and PERMANENT once shipped in a
  tagged release.
- origin is one of "builtin" | "generated" | "graduated". When a tool is
  reimplemented (generated snippet -> hardcoded route -> C# add-in), its name,
  arguments, and result shape must not change; only origin does. That is what
  keeps graduation invisible to MCP clients.

This file runs under IronPython 2.7 inside Revit: no f-strings, no type
annotations, no py3-only stdlib. Keep it boring.

The list below covers the default (trimmed) MCP tool surface. When adding a
tool, adding its manifest entry here is step 5 of the recipe in LLM.txt.
"""
import logging

from pyrevit import routes

logger = logging.getLogger(__name__)

EXTENSION_VERSION = "0.2.0"

MANIFEST = {
    "manifest_version": 1,
    "server": {
        "name": "RevitMCP",
        "extension_version": EXTENSION_VERSION,
    },
    "tools": [
        {
            "name": "execute_revit_code",
            "origin": "builtin",
            "routes": ["POST /execute_code/"],
            "description": "Run IronPython against the open model; the workhorse.",
        },
        {
            "name": "get_revit_status",
            "origin": "builtin",
            "routes": ["GET /status/"],
            "description": "Bridge liveness and document state.",
        },
        {
            "name": "get_revit_model_info",
            "origin": "builtin",
            "routes": ["GET /model_info/"],
            "description": "Document identity and element counts.",
        },
        {
            "name": "get_current_view_info",
            "origin": "builtin",
            "routes": ["GET /current_view_info/"],
            "description": "Active view context.",
        },
        {
            "name": "list_revit_views",
            "origin": "builtin",
            "routes": ["GET /list_views/"],
            "description": "View lookup by name.",
        },
        {
            "name": "get_selected_elements",
            "origin": "builtin",
            "routes": ["GET /selected_elements/"],
            "description": "The user's current selection.",
        },
        {
            "name": "check_element_ownership",
            "origin": "builtin",
            "routes": ["POST /worksharing/ownership/"],
            "description": "Worksharing pre-flight before a bulk edit.",
        },
    ],
}


def register_manifest_routes(api):
    @api.route("/tools/", methods=["GET"])
    def get_tools_manifest():
        return routes.make_response(data=MANIFEST)

    logger.info("Manifest routes registered successfully")
