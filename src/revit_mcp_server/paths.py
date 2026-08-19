# -*- coding: utf-8 -*-
"""Env-independent resolution of the local data root.

MCP clients differ in what environment they pass to spawned servers: Claude
Code inherits everything, Codex passes only explicitly configured vars. With
neither LOCALAPPDATA nor USERPROFILE set, expanduser("~") returns the literal
string "~" and naive path code writes telemetry into a relative './~/'
directory inside the client's sandbox — silently lost. (Found the hard way.)

Resolution order:
1. LOCALAPPDATA env var (normal case)
2. SHGetKnownFolderPath(FOLDERID_LocalAppData) — asks Windows directly,
   needs no environment at all
3. USERPROFILE\\AppData\\Local
4. expanduser("~")\\AppData\\Local, rejected if "~" didn't resolve
5. None — callers must skip writing rather than write to a relative path
"""
import os

_FOLDERID_LOCAL_APP_DATA = "{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}"


def _known_folder_local_appdata():
    try:
        import ctypes
        from ctypes import wintypes

        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32
        guid = ctypes.create_string_buffer(16)
        ole32.CLSIDFromString(_FOLDERID_LOCAL_APP_DATA, guid)
        path_ptr = ctypes.c_wchar_p()
        if shell32.SHGetKnownFolderPath(guid, 0, None, ctypes.byref(path_ptr)) == 0:
            try:
                return path_ptr.value
            finally:
                ctypes.windll.ole32.CoTaskMemFree(path_ptr)
    except Exception:
        pass
    return None


def local_app_data():
    root = os.environ.get("LOCALAPPDATA")
    if root:
        return root
    root = _known_folder_local_appdata()
    if root:
        return root
    profile = os.environ.get("USERPROFILE")
    if profile:
        return os.path.join(profile, "AppData", "Local")
    home = os.path.expanduser("~")
    if home and home != "~":
        if os.name == "nt":
            return os.path.join(home, "AppData", "Local")
        return home
    return None


def data_root():
    """%LOCALAPPDATA%/revit-mcp, or None when no absolute home is resolvable."""
    root = local_app_data()
    return os.path.join(root, "revit-mcp") if root else None
