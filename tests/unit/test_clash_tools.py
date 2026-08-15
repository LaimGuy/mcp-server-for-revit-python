# -*- coding: utf-8 -*-
"""Tests for clash detection tool wrappers (moved here from mep_tools)."""
import pytest

from revit_mcp_server.tools.clash_tools import register_clash_tools


class TestClashTools:
    @pytest.fixture(autouse=True)
    def setup(self, mock_mcp, mock_revit_get, mock_revit_post):
        mock_revit_post.return_value = {"status": "success", "message": "OK"}
        register_clash_tools(mock_mcp, mock_revit_get, mock_revit_post)
        self.tools = mock_mcp.tools
        self.mock_post = mock_revit_post

    async def test_check_clashes_defaults(self):
        await self.tools["check_clashes"](ctx=None)
        self.mock_post.assert_called_once_with(
            "/clash_check/",
            {"set_a_categories": None, "set_b_categories": None, "max_clashes": 200},
            None,
        )

    async def test_check_clashes_cross_discipline(self):
        await self.tools["check_clashes"](
            set_a_categories=["beams"], set_b_categories=["ducts"], max_clashes=10, ctx=None
        )
        call_data = self.mock_post.call_args[0][1]
        assert call_data["set_a_categories"] == ["beams"]
        assert call_data["set_b_categories"] == ["ducts"]
        assert call_data["max_clashes"] == 10
