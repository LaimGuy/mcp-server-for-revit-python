# -*- coding: utf-8 -*-
"""Tool registration system for Revit MCP Server"""

import logging
import os

logger = logging.getLogger(__name__)

# Tools kept when the surface is trimmed, which is the default.
#
# Why trim: an MCP client defers tool *schemas* once the registered surface gets
# large. The full 62-tool surface trips that, so a session's first action becomes
# a ToolSearch round trip just to load a schema before it can touch Revit at all
# - paid on every single session. Keeping the count low keeps schemas eager, so
# the first call reaches the model.
#
# Little is lost by cutting. Every removed tool wraps Revit API calls that
# execute_revit_code can make directly in one payload, which is how this
# workflow operates anyway (see LLM.txt). A trimmed tool is one env var away.
#
# Set REVIT_MCP_ALL_TOOLS=1 to register the full surface.
CORE_TOOLS = frozenset(
    [
        "execute_revit_code",  # the workhorse; everything below is reachable from it
        "get_revit_status",  # is the bridge alive, is a document open
        "get_revit_model_info",  # document identity and counts
        "get_current_view_info",  # cheap active-view context
        "list_revit_views",  # view lookup by name
        "get_selected_elements",  # acting on the user's current selection
        "check_element_ownership",  # worksharing pre-flight before a bulk edit
    ]
)

# Cut for a reason beyond disuse: get_current_view_elements measured 304 B per
# element with no bounded or summary mode, so an ordinary MEP coordination view
# blows the context window in a single call with no warning. Ask
# execute_revit_code for a category tally plus only the ids actually needed.
# (It now has summary=True and this is mitigated, but the trim stands: the
# execute path covers it.)

# Tools created by `revit-mcp promote`. Members survive the trim like
# CORE_TOOLS. Maintained inside the generated fence below — machine-managed.
# >>> revit-mcp:generated-tools:begin
GENERATED_TOOLS = set()
# >>> revit-mcp:generated-tools:end


def _trim_tool_surface(mcp_server):
    """Drop non-core, non-generated tools from the registry. Never fatal."""
    if os.environ.get("REVIT_MCP_ALL_TOOLS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        logger.info("REVIT_MCP_ALL_TOOLS set; registering the full tool surface.")
        return

    try:
        manager = mcp_server._tool_manager
        registered = set(manager._tools.keys())
    except AttributeError:
        logger.warning(
            "MCP server tool registry not accessible; keeping all tools registered."
        )
        return

    keep = CORE_TOOLS | GENERATED_TOOLS
    missing = keep - registered
    if missing:
        logger.warning(
            "Core tools never registered (name drift?): %s", ", ".join(sorted(missing))
        )

    for name in sorted(registered - keep):
        try:
            manager.remove_tool(name)
        except Exception:
            manager._tools.pop(name, None)

    logger.info(
        "Tool surface trimmed to %d of %d. Set REVIT_MCP_ALL_TOOLS=1 to restore.",
        len(manager._tools),
        len(registered),
    )


def register_tools(mcp_server, revit_get_func, revit_post_func, revit_image_func):
    """Register all tools with the MCP server"""
    # Import all tool modules
    from .status_tools import register_status_tools
    from .view_tools import register_view_tools
    from .family_tools import register_family_tools
    from .model_tools import register_model_tools
    from .colors_tools import register_colors_tools
    from .code_execution_tools import register_code_execution_tools
    from .launch_tools import register_launch_tools
    from .document_tools import register_document_tools

    # --- Local additions (keep below upstream imports) ---
    from .worksharing_tools import register_worksharing_tools

    # Merged from Demolinator/revit-mcp-server (MIT)
    from .view_management_tools import register_view_management_tools
    from .documentation_tools import register_documentation_tools
    from .annotation_tools import register_annotation_tools
    from .tag_tools import register_tag_tools
    from .detail_tools import register_detail_tools
    from .editing_tools import register_editing_tools
    from .transform_tools import register_transform_tools
    from .parameter_tools import register_parameter_tools
    from .analysis_tools import register_analysis_tools
    from .clash_tools import register_clash_tools
    from .interop_tools import register_interop_tools

    # Merged from ahmedmgamal/mcp-server-for-revit-python-mep (MIT)
    from .mep_tools import register_mep_tools

    # Hanger tagging (csamp05, MIT) + generic support naming (ours)
    from .hanger_tools import register_hanger_tools

    # --- End local additions ---

    # Register tools from each module
    register_status_tools(mcp_server, revit_get_func)
    register_view_tools(mcp_server, revit_get_func, revit_post_func, revit_image_func)
    register_family_tools(mcp_server, revit_get_func, revit_post_func)
    register_model_tools(mcp_server, revit_get_func)
    register_colors_tools(mcp_server, revit_get_func, revit_post_func)
    register_code_execution_tools(
        mcp_server, revit_get_func, revit_post_func, revit_image_func
    )
    register_launch_tools(mcp_server, revit_get_func)
    register_document_tools(mcp_server, revit_get_func, revit_post_func)

    # --- Local additions (keep below upstream registrations) ---
    register_worksharing_tools(mcp_server, revit_get_func, revit_post_func)

    # Merged from Demolinator/revit-mcp-server (MIT)
    register_view_management_tools(mcp_server, revit_get_func, revit_post_func)
    register_documentation_tools(mcp_server, revit_get_func, revit_post_func)
    register_annotation_tools(mcp_server, revit_get_func, revit_post_func)
    register_tag_tools(mcp_server, revit_get_func, revit_post_func)
    register_detail_tools(mcp_server, revit_get_func, revit_post_func)
    register_editing_tools(mcp_server, revit_get_func, revit_post_func)
    register_transform_tools(mcp_server, revit_get_func, revit_post_func)
    register_parameter_tools(mcp_server, revit_get_func, revit_post_func)
    register_analysis_tools(mcp_server, revit_get_func, revit_post_func)
    register_clash_tools(mcp_server, revit_get_func, revit_post_func)
    register_interop_tools(mcp_server, revit_get_func, revit_post_func)

    # Merged from ahmedmgamal/mcp-server-for-revit-python-mep (MIT)
    register_mep_tools(mcp_server, revit_get_func, revit_post_func)

    # Hanger tagging (csamp05, MIT) + generic support naming (ours)
    register_hanger_tools(mcp_server, revit_get_func, revit_post_func)
    # --- End local additions ---

    # === GENERATED (revit-mcp promote) — edits between markers are machine-managed ===
    # Each entry is its own try/except: a bad generated module must not
    # take down the builtin tools.
    # >>> revit-mcp:generated:begin
    # >>> revit-mcp:generated:end

    # Keep last: everything above registers, then the surface is trimmed to
    # CORE_TOOLS | GENERATED_TOOLS so schemas stay eager on the client.
    _trim_tool_surface(mcp_server)
