# -*- coding: UTF-8 -*-
"""
Revit MCP Extension Startup
Registers all MCP routes and initializes the API
"""

from pyrevit import routes
import logging

logger = logging.getLogger(__name__)

# Initialize the main API
api = routes.API("revit_mcp")


def register_routes():
    """Register all MCP route modules"""
    try:
        # Import and register status routes
        from revit_mcp.status import register_status_routes

        register_status_routes(api)

        from revit_mcp.model_info import register_model_info_routes

        register_model_info_routes(api)

        from revit_mcp.views import register_views_routes

        register_views_routes(api)

        from revit_mcp.placement import register_placement_routes

        register_placement_routes(api)

        from revit_mcp.colors import register_color_routes

        register_color_routes(api)

        from revit_mcp.code_execution import register_code_execution_routes

        register_code_execution_routes(api)

        from revit_mcp.document import register_document_routes

        register_document_routes(api)

        # --- Local additions (keep below upstream registrations) ---
        from revit_mcp.worksharing import register_worksharing_routes

        register_worksharing_routes(api)

        # Merged from Demolinator/revit-mcp-server (MIT)
        from revit_mcp.view_management import register_view_management_routes
        from revit_mcp.documentation import register_documentation_routes
        from revit_mcp.annotation import register_annotation_routes
        from revit_mcp.tags import register_tag_routes
        from revit_mcp.detail import register_detail_routes
        from revit_mcp.editing import register_editing_routes
        from revit_mcp.transforms import register_transform_routes
        from revit_mcp.parameters import register_parameter_routes
        from revit_mcp.analysis import register_analysis_routes
        from revit_mcp.clash import register_clash_routes
        from revit_mcp.interop import register_interop_routes

        register_view_management_routes(api)
        register_documentation_routes(api)
        register_annotation_routes(api)
        register_tag_routes(api)
        register_detail_routes(api)
        register_editing_routes(api)
        register_transform_routes(api)
        register_parameter_routes(api)
        register_analysis_routes(api)
        register_clash_routes(api)
        register_interop_routes(api)

        # Merged from ahmedmgamal/mcp-server-for-revit-python-mep (MIT)
        from revit_mcp.mep import register_mep_routes

        register_mep_routes(api)

        # Hanger tagging engine from csamp05 fork (MIT); naming is our own
        # generic pattern-driven rewrite of their convention-bound module
        from revit_mcp.hangers import register_hanger_routes
        from revit_mcp.support_naming import register_support_naming_routes

        register_hanger_routes(api)
        register_support_naming_routes(api)
        # --- End local additions ---

        # === GENERATED (revit-mcp promote) — edits between markers are machine-managed ===
        # Each generated entry is its own try/except that logs and continues:
        # one bad generated module must never take down the builtin routes.
        # >>> revit-mcp:generated:begin
        # >>> revit-mcp:generated:end

        # Manifest last, so it can describe everything that registered above
        from revit_mcp.manifest import register_manifest_routes

        register_manifest_routes(api)

        logger.info("All MCP routes registered successfully")

    except Exception as e:
        logger.error("Failed to register MCP routes: %s", str(e))
        raise


# Register all routes when the extension loads
register_routes()
