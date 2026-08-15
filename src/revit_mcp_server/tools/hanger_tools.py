# -*- coding: utf-8 -*-
"""Hanger tagging tools"""

from mcp.server.mcpserver import Context
from typing import List, Optional
from .utils import format_response


def register_hanger_tools(mcp, revit_get, revit_post, revit_image=None):
    """Register hanger tools with the MCP server."""

    @mcp.tool()
    async def tag_hangers(
        view_name: Optional[str] = None,
        hanger_category: str = "MEP Fabrication Hangers",
        tag_family_category: str = "MEP Fabrication Hanger Tags",
        avoid_categories: Optional[List[str]] = None,
        retag_existing: bool = False,
        tag_margin: float = 0.3,
        obstacle_margin: float = 0.15,
        ctx: Context = None,
    ) -> str:
        """
        Tag hangers in a Revit view with non-overlapping tags and non-crossing leaders.

        Each hanger gets an IndependentTag with a short, free-end leader. Tags are
        placed by searching increasing leader lengths in multiple directions
        (up, diagonals, sides, down) and picking the shortest one that clears:
        - every other tag's head (no touching/overlapping tag boxes)
        - every other tag's leader (no crossing leader tails)
        - any element in `avoid_categories` (e.g. piping, insulation), if given

        Args:
            view_name: View to tag in. Defaults to the currently active view.
            hanger_category: Category name of the elements to tag (default: "MEP Fabrication Hangers").
            tag_family_category: Category name of the tag family to use (default: "MEP Fabrication Hanger Tags").
            avoid_categories: Category names tags must steer clear of, e.g.
                ["MEP Fabrication Pipework", "Insulation"]. Pass an empty list
                to allow tags to land anywhere (e.g. on top of equipment).
                Defaults to piping and insulation if omitted.
            retag_existing: If True, remove and replace any existing tags on
                these hangers in the view. If False (default), hangers that
                already have a tag in the view are left untouched.
            tag_margin: Minimum clearance in feet required between tag heads (default: 0.3).
            obstacle_margin: Minimum clearance in feet required between a tag
                head and an avoided element (default: 0.15).
            ctx: MCP context for logging

        Returns:
            Summary of the tagging operation: how many were tagged, skipped,
            or could not be cleanly placed, plus leader length statistics.
        """
        try:
            data = {
                "hanger_category": hanger_category,
                "tag_family_category": tag_family_category,
                "retag_existing": retag_existing,
                "tag_margin": tag_margin,
                "obstacle_margin": obstacle_margin,
            }
            if view_name:
                data["view_name"] = view_name
            if avoid_categories is not None:
                data["avoid_categories"] = avoid_categories

            if ctx:
                await ctx.info(
                    "Tagging {} in view {}".format(
                        hanger_category, view_name or "(active view)"
                    )
                )
            response = await revit_post("/tag_hangers/", data, ctx, timeout=120.0)
            return format_response(response)

        except Exception as e:
            error_msg = "Error tagging hangers: {}".format(str(e))
            if ctx:
                await ctx.error(error_msg)
            return error_msg


    @mcp.tool()
    async def name_supports(
        category: str,
        name_param: str = "Mark",
        pattern: str = "{PREFIX}-{LEVEL}-{NNN}",
        prefix: str = "SUP",
        prefix_map: Optional[dict] = None,
        pad: int = 3,
        skip_family_keywords: Optional[List[str]] = None,
        dry_run: bool = False,
        ctx: Context = None,
    ) -> str:
        """
        Name every unnamed element of a category using a configurable pattern.

        Pattern tokens: {PREFIX}, {LEVEL}, {NNN}. Default "{PREFIX}-{LEVEL}-{NNN}"
        produces names like SUP-L01-001. Sequences run per (prefix, level) group
        and continue from the highest number already used in the model (parsed
        from existing names with the same pattern), so numbers are never
        reissued. Within a group, new elements are numbered along a
        nearest-neighbour walk from the group's last-named element, so numbers
        follow the physical run.

        Elements whose name parameter already has a value are never touched
        (whether or not it matches the pattern).

        Args:
            category: Category of elements to name (e.g. "Electrical Equipment",
                "Conduit Fittings", "MEP Fabrication Hangers"). Required.
            name_param: Parameter to write (default "Mark").
            pattern: Naming pattern containing {PREFIX}, {LEVEL} and {NNN}.
            prefix: Fixed prefix used when prefix_map has no match (default "SUP").
            prefix_map: Optional case-insensitive map of family-name keyword ->
                prefix, first match wins (e.g. {"strut": "TH", "clevis": "CL"}).
            pad: Zero-padding width for {NNN} (default 3).
            skip_family_keywords: Elements whose family name contains any of
                these keywords are left unnamed.
            dry_run: If True, report planned names without modifying the model.
            ctx: MCP context for logging

        Returns:
            Per-group summary: planned/applied counts, sample names, skips.
        """
        try:
            data = {
                "category": category,
                "name_param": name_param,
                "pattern": pattern,
                "prefix": prefix,
                "pad": pad,
                "dry_run": dry_run,
            }
            if prefix_map:
                data["prefix_map"] = prefix_map
            if skip_family_keywords:
                data["skip_family_keywords"] = skip_family_keywords

            if ctx:
                await ctx.info(
                    "Naming {}{}".format(category, " (dry run)" if dry_run else "")
                )
            response = await revit_post("/name_supports/", data, ctx, timeout=120.0)
            return format_response(response)

        except Exception as e:
            error_msg = "Error naming supports: {}".format(str(e))
            if ctx:
                await ctx.error(error_msg)
            return error_msg
