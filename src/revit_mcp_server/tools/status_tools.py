# -*- coding: utf-8 -*-
"""Status and model information tools"""

from mcp.server.mcpserver import Context
from .utils import format_response


def register_status_tools(mcp, revit_get):
    """Register status-related tools"""

    @mcp.tool()
    async def get_revit_status(ctx: Context) -> str:
        """Check if the Revit MCP API is active and responding"""
        response = await revit_get("/status/", ctx, timeout=10.0)
        return format_response(response)

    @mcp.tool()
    async def get_revit_model_info(list_cap: int = 50, ctx: Context = None) -> str:
        """Get comprehensive information about the current Revit model.

        List-valued fields (levels, linked models, ...) are capped at list_cap
        entries each; a <field>_total count is added when a cap trims one.

        Args:
            list_cap: Max entries per list field (default 50).
        """
        response = await revit_get("/model_info/", ctx)
        if isinstance(response, dict):
            response = _cap_lists(response, list_cap)
        return format_response(response)


def _cap_lists(payload, cap):
    """Recursively cap list fields, recording <key>_total beside trimmed ones."""
    if isinstance(payload, dict):
        out = {}
        for key, value in payload.items():
            if isinstance(value, list) and len(value) > cap:
                out[key] = value[:cap]
                out[key + "_total"] = len(value)
            elif isinstance(value, dict):
                out[key] = _cap_lists(value, cap)
            else:
                out[key] = value
        return out
    return payload
