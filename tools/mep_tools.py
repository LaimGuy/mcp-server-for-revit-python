# -*- coding: utf-8 -*-
"""MEP tools: linear system creation, network topology, and system analysis"""

from mcp.server.fastmcp import Context
from typing import Optional
from .utils import format_response


def register_mep_tools(mcp, revit_get, revit_post):
    """Register MEP-related tools with the MCP server"""

    # ---- A. Cable Containment & Piping (Linear Systems) ----

    @mcp.tool()
    async def create_pipe(
        start_x: float,
        start_y: float,
        start_z: float,
        end_x: float,
        end_y: float,
        end_z: float,
        diameter_mm: float,
        system_type_name: Optional[str] = None,
        pipe_type_name: Optional[str] = None,
        level_name: Optional[str] = None,
        ctx: Context = None,
    ) -> str:
        """
        Create a physical pipe run between two points in the Revit model.

        Args:
            start_x, start_y, start_z: Start point coordinates (feet)
            end_x, end_y, end_z: End point coordinates (feet)
            diameter_mm: Pipe diameter in millimeters
            system_type_name: Name of the piping system type (e.g. "Domestic Cold Water")
            pipe_type_name: Name of the pipe type/routing preference (defaults to first available)
            level_name: Name of the level to host the pipe (defaults to nearest to start point)
        """
        data = {
            "start": {"x": start_x, "y": start_y, "z": start_z},
            "end": {"x": end_x, "y": end_y, "z": end_z},
            "diameter_mm": diameter_mm,
            "system_type_name": system_type_name,
            "pipe_type_name": pipe_type_name,
            "level_name": level_name,
        }
        response = await revit_post("/create_pipe/", data, ctx)
        return format_response(response)

    @mcp.tool()
    async def create_sloped_pipe(
        start_x: float,
        start_y: float,
        start_z: float,
        end_x: float,
        end_y: float,
        end_z: float,
        slope: float,
        diameter_mm: float,
        system_type_name: Optional[str] = None,
        pipe_type_name: Optional[str] = None,
        level_name: Optional[str] = None,
        ctx: Context = None,
    ) -> str:
        """
        Create a sloped pipe run for drainage/sanitary systems, applying a
        slope ratio via the Revit API's Slope parameter.

        Args:
            start_x, start_y, start_z: Start point coordinates (feet)
            end_x, end_y, end_z: End point coordinates (feet)
            slope: Slope ratio to apply (e.g. 0.01 for a 1% drop)
            diameter_mm: Pipe diameter in millimeters
            system_type_name: Name of the piping system type (e.g. "Sanitary")
            pipe_type_name: Name of the pipe type/routing preference (defaults to first available)
            level_name: Name of the level to host the pipe (defaults to nearest to start point)
        """
        data = {
            "start": {"x": start_x, "y": start_y, "z": start_z},
            "end": {"x": end_x, "y": end_y, "z": end_z},
            "slope": slope,
            "diameter_mm": diameter_mm,
            "system_type_name": system_type_name,
            "pipe_type_name": pipe_type_name,
            "level_name": level_name,
        }
        response = await revit_post("/create_sloped_pipe/", data, ctx)
        return format_response(response)

    @mcp.tool()
    async def create_duct(
        start_x: float,
        start_y: float,
        start_z: float,
        end_x: float,
        end_y: float,
        end_z: float,
        width_mm: Optional[float] = None,
        height_mm: Optional[float] = None,
        diameter_mm: Optional[float] = None,
        system_type_name: Optional[str] = None,
        duct_type_name: Optional[str] = None,
        level_name: Optional[str] = None,
        ctx: Context = None,
    ) -> str:
        """
        Create a physical duct run between two points in the Revit model.

        For rectangular ducts pass width_mm and height_mm. For round ducts
        pass diameter_mm instead.

        Args:
            start_x, start_y, start_z: Start point coordinates (feet)
            end_x, end_y, end_z: End point coordinates (feet)
            width_mm: Rectangular duct width in millimeters
            height_mm: Rectangular duct height in millimeters
            diameter_mm: Round duct diameter in millimeters
            system_type_name: Name of the mechanical system type (e.g. "Supply Air")
            duct_type_name: Name of the duct type (defaults to first available)
            level_name: Name of the level to host the duct (defaults to nearest to start point)
        """
        data = {
            "start": {"x": start_x, "y": start_y, "z": start_z},
            "end": {"x": end_x, "y": end_y, "z": end_z},
            "width_mm": width_mm,
            "height_mm": height_mm,
            "diameter_mm": diameter_mm,
            "system_type_name": system_type_name,
            "duct_type_name": duct_type_name,
            "level_name": level_name,
        }
        response = await revit_post("/create_duct/", data, ctx)
        return format_response(response)

    @mcp.tool()
    async def create_cable_tray(
        start_x: float,
        start_y: float,
        start_z: float,
        end_x: float,
        end_y: float,
        end_z: float,
        width_mm: float,
        height_mm: float,
        cable_tray_type_name: Optional[str] = None,
        level_name: Optional[str] = None,
        ctx: Context = None,
    ) -> str:
        """
        Create an electrical cable tray run between two points, for routing
        cable containment around structural objects.

        Args:
            start_x, start_y, start_z: Start point coordinates (feet)
            end_x, end_y, end_z: End point coordinates (feet)
            width_mm: Cable tray width in millimeters
            height_mm: Cable tray height in millimeters
            cable_tray_type_name: Name of the cable tray type (defaults to first available)
            level_name: Name of the level to host the tray (defaults to nearest to start point)
        """
        data = {
            "start": {"x": start_x, "y": start_y, "z": start_z},
            "end": {"x": end_x, "y": end_y, "z": end_z},
            "width_mm": width_mm,
            "height_mm": height_mm,
            "cable_tray_type_name": cable_tray_type_name,
            "level_name": level_name,
        }
        response = await revit_post("/create_cable_tray/", data, ctx)
        return format_response(response)

    @mcp.tool()
    async def create_conduit(
        start_x: float,
        start_y: float,
        start_z: float,
        end_x: float,
        end_y: float,
        end_z: float,
        diameter_mm: float,
        conduit_type_name: Optional[str] = None,
        level_name: Optional[str] = None,
        ctx: Context = None,
    ) -> str:
        """
        Create an electrical conduit run between two points, for routing
        cable containment around structural objects.

        Args:
            start_x, start_y, start_z: Start point coordinates (feet)
            end_x, end_y, end_z: End point coordinates (feet)
            diameter_mm: Conduit diameter in millimeters
            conduit_type_name: Name of the conduit type (defaults to first available)
            level_name: Name of the level to host the conduit (defaults to nearest to start point)
        """
        data = {
            "start": {"x": start_x, "y": start_y, "z": start_z},
            "end": {"x": end_x, "y": end_y, "z": end_z},
            "diameter_mm": diameter_mm,
            "conduit_type_name": conduit_type_name,
            "level_name": level_name,
        }
        response = await revit_post("/create_conduit/", data, ctx)
        return format_response(response)

    # ---- B. Logical Connections & Network Topology ----

    @mcp.tool()
    async def get_mep_systems(
        system_type: str = "all",
        name_contains: Optional[str] = None,
        ctx: Context = None,
    ) -> str:
        """
        Map the MEP system tree in the model - which elements are logically
        connected to which piping, duct or electrical system, and which
        equipment serves each system (e.g. which VAV boxes are connected to
        Air Handling Unit 1).

        Args:
            system_type: "piping", "duct", "electrical", or "all" (default "all")
            name_contains: Optional case-insensitive substring filter on system name
        """
        data = {"system_type": system_type}
        if name_contains:
            data["name_contains"] = name_contains
        response = await revit_post("/get_mep_systems/", data, ctx)
        return format_response(response)

    @mcp.tool()
    async def connect_elements(
        element_id_1: int,
        element_id_2: int,
        ctx: Context = None,
    ) -> str:
        """
        Explicitly connect two MEP components using their native Revit
        Connectors, e.g. snapping a pipe precisely to the flow/return
        connectors on a mechanical pump. Uses the nearest pair of open,
        compatible connectors found on the two elements.

        Args:
            element_id_1: Element ID of the first component
            element_id_2: Element ID of the second component
        """
        data = {"element_id_1": element_id_1, "element_id_2": element_id_2}
        response = await revit_post("/connect_elements/", data, ctx)
        return format_response(response)

    # ---- C. System Engineering Analysis ----

    @mcp.tool()
    async def read_panel_schedule(panel_name: str, ctx: Context = None) -> str:
        """
        Extract electrical load summary, circuit numbers and phase balance
        from a specified distribution board (electrical panel).

        Args:
            panel_name: Name of the electrical equipment (panel) to read
        """
        data = {"panel_name": panel_name}
        response = await revit_post("/read_panel_schedule/", data, ctx)
        return format_response(response)

    @mcp.tool()
    async def check_mep_clashes(
        category_a: str,
        category_b: str,
        limit: int = 25,
        ctx: Context = None,
    ) -> str:
        """
        Run a localized clash detection routine between two categories (e.g.
        Mechanical Ducts vs. Structural Framing) so the AI can self-correct
        routing errors.

        Renamed from check_clashes to avoid colliding with the general
        clash_tools.check_clashes (Demolinator); this one is the narrow
        two-category MEP variant hitting /check_clashes/.

        Args:
            category_a: First category to check (e.g. "Ducts")
            category_b: Second category to check (e.g. "Structural Framing")
            limit: Maximum number of clashes to return (default 25)
        """
        data = {"category_a": category_a, "category_b": category_b, "limit": limit}
        response = await revit_post("/check_clashes/", data, ctx, timeout=60.0)
        return format_response(response)
