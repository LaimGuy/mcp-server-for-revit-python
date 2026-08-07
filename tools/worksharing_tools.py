# -*- coding: utf-8 -*-
"""Worksharing tools: worksets, ownership, reload latest, relinquish.

Sync-with-central lives in document_tools.py; these tools cover the workset
and ownership side of collaborating in a shared central model.
"""

from typing import List, Optional

from mcp.server.fastmcp import Context

from .utils import format_response


def _as_error(response):
    """Return an error string if the response is an error, else None."""
    if isinstance(response, str):
        return response
    if isinstance(response, dict) and "error" in response:
        return "Error: {}".format(response["error"])
    return None


def register_worksharing_tools(mcp, revit_get, revit_post):
    """Register worksharing-related tools."""

    @mcp.tool()
    async def get_worksharing_status(ctx: Context) -> str:
        """Report whether the active model is workshared and how it is set up.

        Shows the central and local paths, whether this is the central model
        or a local copy, the current Revit user, the active workset, and how
        many worksets you versus other people currently own.

        Run this before any bulk edit on a shared project.
        """
        response = await revit_get("/worksharing/status/", ctx, timeout=30.0)
        err = _as_error(response)
        if err:
            return err

        if not response.get("is_workshared"):
            return (
                "Model '{}' is NOT workshared.\n"
                "Path: {}\n"
                "Workset and ownership operations do not apply; edits are "
                "unrestricted.".format(
                    response.get("document_title"), response.get("local_path")
                )
            )

        lines = ["=== WORKSHARING STATUS ==="]
        lines.append("Document: {}".format(response.get("document_title")))
        lines.append("Model role: {}".format(response.get("model_role")))
        lines.append("Current user: {}".format(response.get("current_user")))
        lines.append("Central: {}".format(response.get("central_path")))
        lines.append("Local: {}".format(response.get("local_path")))
        lines.append(
            "Active workset: {} (id {})".format(
                response.get("active_workset_name"),
                response.get("active_workset_id"),
            )
        )
        lines.append(
            "User worksets: {} total | {} owned by you | {} owned by others".format(
                response.get("user_workset_count"),
                response.get("worksets_owned_by_you"),
                response.get("worksets_owned_by_others"),
            )
        )
        if response.get("model_role") == "central":
            lines.append("")
            lines.append(
                "WARNING: this is the central model opened directly, not a "
                "local copy. Editing the central model directly is usually a "
                "mistake on a team project."
            )
        return "\n".join(lines)

    @mcp.tool()
    async def list_worksets(ctx: Context) -> str:
        """List all user worksets with their owner and open/editable state.

        Use this to find the right workset id or name before creating
        elements, moving elements, or diagnosing why something is not
        editable.
        """
        response = await revit_get("/worksharing/worksets/", ctx, timeout=30.0)
        err = _as_error(response)
        if err:
            return err

        worksets = response.get("worksets", [])
        if not worksets:
            return "No user worksets found."

        lines = [
            "=== WORKSETS ({} total, user: {}) ===".format(
                response.get("workset_count"), response.get("current_user")
            )
        ]
        for ws in worksets:
            flags = []
            if ws.get("is_active"):
                flags.append("ACTIVE")
            if not ws.get("is_open"):
                flags.append("closed")
            if not ws.get("is_visible_by_default"):
                flags.append("hidden-by-default")

            owner = ws.get("owner")
            if ws.get("owned_by_you"):
                owner_text = "owned by you"
            elif owner:
                owner_text = "OWNED BY {}".format(owner)
            else:
                owner_text = "unowned"

            lines.append(
                "  [{}] {} - {}{}".format(
                    ws.get("id"),
                    ws.get("name"),
                    owner_text,
                    " ({})".format(", ".join(flags)) if flags else "",
                )
            )
        return "\n".join(lines)

    @mcp.tool()
    async def check_element_ownership(
        ctx: Context,
        element_ids: Optional[List[int]] = None,
        category: Optional[str] = None,
        workset_id: Optional[int] = None,
        limit: int = 500,
        include_details: bool = False,
    ) -> str:
        """Check which elements you can actually edit right now.

        This is a pre-flight check for workshared models: it reports which
        elements are owned by other users and would cause an edit to fail.
        Run it before any bulk modification so the operation does not fail
        partway through.

        Provide exactly one selector:
            element_ids: explicit element ids to check
            category: a BuiltInCategory name such as OST_Walls
            workset_id: check everything on one workset

        Args:
            element_ids: Explicit list of element ids.
            category: BuiltInCategory name, e.g. "OST_StructuralFraming".
            workset_id: Workset id to check.
            limit: Max elements to check (default 500).
            include_details: Include per-element creator/owner/last-changed-by.
        """
        payload = {"limit": limit, "include_details": include_details}
        if element_ids:
            payload["element_ids"] = element_ids
        if category:
            payload["category"] = category
        if workset_id is not None:
            payload["workset_id"] = workset_id

        response = await revit_post(
            "/worksharing/ownership/", payload, ctx, timeout=120.0
        )
        err = _as_error(response)
        if err:
            return err

        counts = response.get("counts", {})
        lines = ["=== OWNERSHIP PRE-FLIGHT ==="]
        lines.append("Scope: {}".format(response.get("scope")))
        lines.append("Checked: {} element(s)".format(response.get("checked")))
        lines.append(
            "Editable now: {} ({} already yours, {} unowned)".format(
                response.get("editable_now"),
                counts.get("owned_by_you"),
                counts.get("not_owned"),
            )
        )
        lines.append("Blocked by others: {}".format(response.get("blocked_by_others")))

        if response.get("safe_to_edit_all"):
            lines.append("")
            lines.append("SAFE: no elements are owned by other users.")
        else:
            lines.append("")
            lines.append("BLOCKED BY:")
            for owner in response.get("blocking_owners", []):
                lines.append(
                    "  {} - {} element(s)".format(
                        owner.get("owner"), owner.get("element_count")
                    )
                )
            blocked_ids = response.get("blocked_element_ids", [])
            if blocked_ids:
                lines.append(
                    "Blocked ids (first {}): {}".format(
                        len(blocked_ids),
                        ", ".join(str(i) for i in blocked_ids),
                    )
                )
            lines.append("")
            lines.append(
                "Those users must sync and relinquish before you can edit "
                "these elements."
            )

        if include_details and response.get("details"):
            lines.append("")
            lines.append("=== DETAILS ===")
            for d in response["details"][:50]:
                lines.append(
                    "  {} | {} | owner={} | creator={} | last changed by={}".format(
                        d.get("id"),
                        d.get("status"),
                        d.get("owner"),
                        d.get("creator"),
                        d.get("last_changed_by"),
                    )
                )

        return "\n".join(lines)

    @mcp.tool()
    async def set_active_workset(
        ctx: Context,
        workset_id: Optional[int] = None,
        workset_name: Optional[str] = None,
    ) -> str:
        """Set the active workset so new elements are created on the right one.

        Revit assigns newly created elements to the active workset. Set this
        before creating elements, otherwise they land on whatever workset
        happened to be active and have to be moved later.

        Args:
            workset_id: Target workset id.
            workset_name: Target workset name (used if no id given).
        """
        payload = {}
        if workset_id is not None:
            payload["workset_id"] = workset_id
        if workset_name:
            payload["workset_name"] = workset_name

        response = await revit_post(
            "/worksharing/set_active_workset/", payload, ctx, timeout=30.0
        )
        return format_response(response)

    @mcp.tool()
    async def create_workset(
        ctx: Context, name: str, set_active: bool = False
    ) -> str:
        """Create a new user workset.

        Args:
            name: Name for the new workset. Must be unique.
            set_active: Make it the active workset immediately.
        """
        response = await revit_post(
            "/worksharing/create_workset/",
            {"name": name, "set_active": set_active},
            ctx,
            timeout=60.0,
        )
        return format_response(response)

    @mcp.tool()
    async def move_elements_to_workset(
        ctx: Context,
        target_workset_id: Optional[int] = None,
        target_workset_name: Optional[str] = None,
        element_ids: Optional[List[int]] = None,
        category: Optional[str] = None,
        limit: int = 500,
    ) -> str:
        """Move elements onto a different workset.

        Elements owned by other users are skipped rather than failing the
        whole operation; the result reports how many were skipped and why.

        Args:
            target_workset_id: Destination workset id.
            target_workset_name: Destination workset name (if no id given).
            element_ids: Explicit element ids to move.
            category: BuiltInCategory name to move instead, e.g. OST_Walls.
            limit: Max elements to move (default 500).
        """
        payload = {"limit": limit}
        if target_workset_id is not None:
            payload["target_workset_id"] = target_workset_id
        if target_workset_name:
            payload["target_workset_name"] = target_workset_name
        if element_ids:
            payload["element_ids"] = element_ids
        if category:
            payload["category"] = category

        response = await revit_post(
            "/worksharing/move_to_workset/", payload, ctx, timeout=180.0
        )
        err = _as_error(response)
        if err:
            return err

        lines = ["=== MOVE TO WORKSET ==="]
        lines.append("Scope: {}".format(response.get("scope")))
        lines.append("Target workset: {}".format(response.get("target_workset")))
        lines.append("Moved: {}".format(response.get("moved")))
        if response.get("skipped_owned_by_others"):
            lines.append(
                "Skipped (owned by others): {}".format(
                    response.get("skipped_owned_by_others")
                )
            )
        if response.get("skipped_not_assignable"):
            lines.append(
                "Skipped (workset not assignable): {}".format(
                    response.get("skipped_not_assignable")
                )
            )
        if response.get("failed"):
            lines.append("Failed: {}".format(response.get("failed")))
            for f in response.get("failures", []):
                lines.append("  {}: {}".format(f.get("id"), f.get("error")))
        return "\n".join(lines)

    @mcp.tool()
    async def reload_latest_from_central(ctx: Context) -> str:
        """Pull the latest changes from central without pushing your own.

        Cheaper and less disruptive than a full sync. Use it before starting
        work, or to pick up someone else's change without publishing your
        in-progress edits.
        """
        response = await revit_post(
            "/worksharing/reload_latest/", {}, ctx, timeout=300.0
        )
        return format_response(response)

    @mcp.tool()
    async def relinquish_ownership(
        ctx: Context,
        checked_out_elements: bool = True,
        user_worksets: bool = True,
        view_worksets: bool = True,
        family_worksets: bool = True,
        standard_worksets: bool = True,
    ) -> str:
        """Release ownership of borrowed elements and worksets.

        Unblocks teammates without doing a full sync. Revit only releases
        items that have no unsynchronized changes; anything you have actually
        modified stays checked out until you sync with central first.

        Args:
            checked_out_elements: Release individually borrowed elements.
            user_worksets: Release owned user worksets.
            view_worksets: Release owned view worksets.
            family_worksets: Release owned family worksets.
            standard_worksets: Release owned project standard worksets.
        """
        response = await revit_post(
            "/worksharing/relinquish/",
            {
                "checked_out_elements": checked_out_elements,
                "user_worksets": user_worksets,
                "view_worksets": view_worksets,
                "family_worksets": family_worksets,
                "standard_worksets": standard_worksets,
            },
            ctx,
            timeout=300.0,
        )
        return format_response(response)
