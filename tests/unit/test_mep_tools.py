# -*- coding: utf-8 -*-
"""Tests for MEP tool wrappers — verify endpoints and payloads."""
import pytest
from revit_mcp_server.tools.mep_tools import register_mep_tools


class TestMepTools:
    @pytest.fixture(autouse=True)
    def setup(self, mock_mcp, mock_revit_get, mock_revit_post):
        mock_revit_post.return_value = {"status": "success"}
        register_mep_tools(mock_mcp, mock_revit_get, mock_revit_post)
        self.tools = mock_mcp.tools
        self.mock_post = mock_revit_post

    async def test_create_pipe(self):
        await self.tools["create_pipe"](
            start_x=0.0, start_y=0.0, start_z=0.0,
            end_x=10.0, end_y=0.0, end_z=0.0,
            diameter_mm=100,
            system_type_name="Domestic Cold Water",
            pipe_type_name="Standard",
            level_name="Level 1",
            ctx=None,
        )
        self.mock_post.assert_called_once_with(
            "/create_pipe/",
            {
                "start": {"x": 0.0, "y": 0.0, "z": 0.0},
                "end": {"x": 10.0, "y": 0.0, "z": 0.0},
                "diameter_mm": 100,
                "system_type_name": "Domestic Cold Water",
                "pipe_type_name": "Standard",
                "level_name": "Level 1",
            },
            None,
        )

    async def test_create_sloped_pipe(self):
        await self.tools["create_sloped_pipe"](
            start_x=0.0, start_y=0.0, start_z=10.0,
            end_x=20.0, end_y=0.0, end_z=9.8,
            slope=0.01,
            diameter_mm=150,
            system_type_name="Sanitary",
            ctx=None,
        )
        call_data = self.mock_post.call_args[0][1]
        assert call_data["slope"] == 0.01
        assert call_data["diameter_mm"] == 150
        assert call_data["system_type_name"] == "Sanitary"
        assert self.mock_post.call_args[0][0] == "/create_sloped_pipe/"

    async def test_create_duct_rectangular(self):
        await self.tools["create_duct"](
            start_x=0.0, start_y=0.0, start_z=0.0,
            end_x=10.0, end_y=0.0, end_z=0.0,
            width_mm=400, height_mm=200,
            system_type_name="Supply Air",
            ctx=None,
        )
        call_data = self.mock_post.call_args[0][1]
        assert call_data["width_mm"] == 400
        assert call_data["height_mm"] == 200
        assert call_data["diameter_mm"] is None

    async def test_create_duct_round(self):
        await self.tools["create_duct"](
            start_x=0.0, start_y=0.0, start_z=0.0,
            end_x=10.0, end_y=0.0, end_z=0.0,
            diameter_mm=250,
            ctx=None,
        )
        call_data = self.mock_post.call_args[0][1]
        assert call_data["diameter_mm"] == 250
        assert call_data["width_mm"] is None
        assert call_data["height_mm"] is None

    async def test_create_cable_tray(self):
        await self.tools["create_cable_tray"](
            start_x=0.0, start_y=0.0, start_z=0.0,
            end_x=5.0, end_y=0.0, end_z=0.0,
            width_mm=300, height_mm=100,
            ctx=None,
        )
        self.mock_post.assert_called_once_with(
            "/create_cable_tray/",
            {
                "start": {"x": 0.0, "y": 0.0, "z": 0.0},
                "end": {"x": 5.0, "y": 0.0, "z": 0.0},
                "width_mm": 300,
                "height_mm": 100,
                "cable_tray_type_name": None,
                "level_name": None,
            },
            None,
        )

    async def test_create_conduit(self):
        await self.tools["create_conduit"](
            start_x=0.0, start_y=0.0, start_z=0.0,
            end_x=5.0, end_y=0.0, end_z=0.0,
            diameter_mm=25,
            ctx=None,
        )
        self.mock_post.assert_called_once_with(
            "/create_conduit/",
            {
                "start": {"x": 0.0, "y": 0.0, "z": 0.0},
                "end": {"x": 5.0, "y": 0.0, "z": 0.0},
                "diameter_mm": 25,
                "conduit_type_name": None,
                "level_name": None,
            },
            None,
        )

    async def test_get_mep_systems_default(self):
        await self.tools["get_mep_systems"](ctx=None)
        self.mock_post.assert_called_once_with(
            "/get_mep_systems/", {"system_type": "all"}, None
        )

    async def test_get_mep_systems_with_filter(self):
        await self.tools["get_mep_systems"](
            system_type="duct", name_contains="AHU-1", ctx=None
        )
        call_data = self.mock_post.call_args[0][1]
        assert call_data["system_type"] == "duct"
        assert call_data["name_contains"] == "AHU-1"

    async def test_connect_elements(self):
        await self.tools["connect_elements"](
            element_id_1=111, element_id_2=222, ctx=None
        )
        self.mock_post.assert_called_once_with(
            "/connect_elements/",
            {"element_id_1": 111, "element_id_2": 222},
            None,
        )

    async def test_read_panel_schedule(self):
        await self.tools["read_panel_schedule"](panel_name="Panel A1", ctx=None)
        self.mock_post.assert_called_once_with(
            "/read_panel_schedule/", {"panel_name": "Panel A1"}, None
        )

