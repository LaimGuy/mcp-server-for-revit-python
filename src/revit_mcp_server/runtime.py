# -*- coding: utf-8 -*-
"""Per-process runtime identity.

One MCP server process = one client session (stdio transport), so a process-
scoped id is a session id. It lets the telemetry distinguish "three failed
attempts then a success" (a converging snippet — the promotion signal) from
four unrelated calls.
"""
import uuid

SESSION_ID = uuid.uuid4().hex[:12]
