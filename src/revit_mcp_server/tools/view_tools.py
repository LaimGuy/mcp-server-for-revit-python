# -*- coding: utf-8 -*-
"""View-related tools for capturing and listing Revit views"""

from mcp.server.mcpserver import Context
from .utils import format_response


def register_view_tools(mcp, revit_get, revit_post, revit_image):
    """Register view-related tools"""

    @mcp.tool()
    async def get_revit_view(view_name: str, ctx: Context = None):
        """Export a specific Revit view as an image"""
        return await revit_image(f"/get_view/{view_name}", ctx)

    @mcp.tool()
    async def list_revit_views(
        name_contains: str = None,
        limit: int = 200,
        summary: bool = False,
        ctx: Context = None,
    ) -> str:
        """Get a list of exportable views in the current Revit model.

        Args:
            name_contains: Case-insensitive substring filter on view names.
            limit: Maximum view names to return across all types (default 200).
            summary: Return only per-type counts, no names. Use this first on
                large models, then filter with name_contains.
        """
        response = await revit_get("/list_views/", ctx)
        if isinstance(response, dict) and "views_by_type" in response:
            by_type = response["views_by_type"]
            if summary:
                response = {
                    "status": "success",
                    "view_counts_by_type": {k: len(v) for k, v in by_type.items()},
                    "total_exportable_views": response.get("total_exportable_views"),
                }
            else:
                needle = name_contains.lower() if name_contains else None
                total_matched = 0
                shown = 0
                bounded = {}
                for vtype, names in by_type.items():
                    if needle is not None:
                        names = [n for n in names if needle in n.lower()]
                    total_matched += len(names)
                    take = max(0, limit - shown)
                    bounded[vtype] = names[:take]
                    shown += len(bounded[vtype])
                response = {
                    "status": "success",
                    "views_by_type": {k: v for k, v in bounded.items() if v},
                    "total_matched": total_matched,
                    "shown": shown,
                    "truncated": shown < total_matched,
                }
                if response["truncated"]:
                    response["message"] = (
                        f"Showing {shown} of {total_matched} views; raise limit "
                        "or narrow name_contains for the rest."
                    )
        return format_response(response)

    @mcp.tool()
    async def get_current_view_info(ctx: Context = None) -> str:
        """
        Get detailed information about the currently active view in Revit.

        Returns comprehensive information including:
        - View name, type, and ID
        - Scale and detail level
        - Crop box status
        - View family type
        - View discipline
        - Template status
        """
        if ctx:
            await ctx.info("Getting current view information...")
        response = await revit_get("/current_view_info/", ctx)
        return format_response(response)

    @mcp.tool()
    async def get_current_view_elements(
        limit: int = 5000,
        include_levels: bool = False,
        include_location: bool = False,
        summary: bool = False,
        ctx: Context = None,
    ) -> str:
        """
        Get elements visible in the currently active view in Revit.

        Returns per element: element_id, name, category, category_id.
        Also returns category_counts (always for ALL elements, even if truncated).

        If the response contains truncated=true, not all elements were returned.
        Check total_elements vs returned_elements and increase limit if needed.

        Start with summary=True on unfamiliar views: it returns only
        category_counts and totals (a full element dump of a coordination
        view can exceed 500KB).

        Args:
            limit: Maximum number of elements to return (default 5000).
            include_levels: Include level name and level_id per element. Default false.
            include_location: Include location geometry (point or curve). Default false.
            summary: Return only category counts and totals, no element list.
        """
        if ctx:
            await ctx.info("Getting elements in current view...")
        data = {
            "limit": limit,
            "include_levels": include_levels,
            "include_location": include_location,
        }
        response = await revit_post("/current_view_elements/", data, ctx)
        if summary and isinstance(response, dict):
            response.pop("elements", None)
            response.pop("truncated", None)
        return format_response(response)
