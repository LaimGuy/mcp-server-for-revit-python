# -*- coding: utf-8 -*-
"""Code execution tools for the MCP server."""

from mcp.server.mcpserver import Context
from .utils import format_response


def register_code_execution_tools(mcp, revit_get, revit_post, revit_image=None):
    """Register code execution tools with the MCP server."""
    # Note: revit_get and revit_image are unused but kept for interface consistency
    _ = revit_get, revit_image  # Acknowledge unused parameters

    @mcp.tool()
    async def execute_revit_code(
        code: str, description: str = "Code execution", ctx: Context = None
    ) -> str:
        """
        Execute IronPython code in the Revit context. One payload does the whole
        job: collect, classify, and write together.

        Injected namespace: doc, uidoc, DB, revit, print, plus helpers —
          safe_tx(doc, name)      started transaction, modal-free. ALWAYS this,
                                  never a bare DB.Transaction (a routine warning
                                  goes modal and hangs the bridge until a human
                                  clicks it). Caller owns Commit().
          suppress_warnings(t)    same handling for a transaction you built
          model_elements(doc, bic=None, view_id=None)
                                  collector with Materials excluded
          safe_name(el)           Element.Name is shadowed under IronPython
          family_name(el)         family name of an instance or symbol

        safe_name/family_name return None on a miss, never a placeholder. Do not
        substitute getattr(el, 'Name', 'N/A'): the placeholder makes every name
        comparison silently miss, and the job reports "0 found" instead of failing.

        No transaction is opened for you. Anything not needing one (reads, and UI
        ops like uidoc.ActiveView = view) must stay outside a transaction.

        Returns printed output only — the script is not echoed back. On failure,
        read the traceback's line number against the script you sent.
        """
        try:
            payload = {"code": code, "description": description}

            if ctx:
                await ctx.info("Executing code: {}".format(description))

            response = await revit_post("/execute_code/", payload, ctx, timeout=60.0)
            return format_response(response)

        except (ConnectionError, ValueError, RuntimeError) as e:
            error_msg = "Error during code execution: {}".format(str(e))
            if ctx:
                await ctx.error(error_msg)
            return error_msg
