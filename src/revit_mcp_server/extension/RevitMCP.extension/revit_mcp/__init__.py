# -*- coding: UTF-8 -*-
"""
MCP Module for Revit Integration
Contains all MCP route handlers organized by functionality
"""

# Version lives in the sibling VERSION file (read by manifest.py) — the single
# source of truth is revit_mcp_server.__version__, stamped there at release.
__author__ = "Juan D. Rodriguez, Jean-Marc Couffin"

# Common imports that all modules might need
import logging

# Make logger available to all submodules
logger = logging.getLogger(__name__)