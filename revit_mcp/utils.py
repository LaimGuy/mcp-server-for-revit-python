# -*- coding: utf-8 -*-
from pyrevit import DB
import traceback
import logging

logger = logging.getLogger(__name__)


def normalize_string(text):
    """Safely normalize string values, always returning a unicode string.

    In IronPython 2, calling str() on a .NET System.String that contains
    non-ASCII characters (e.g. accented letters) produces a byte string
    encoded with the system default codec.  The pyRevit Routes JSON encoder
    then fails with 'unknown codec can't decode byte 0xNN'.

    By returning unicode we guarantee the JSON serialiser receives a proper
    text object regardless of the locale of the Revit model.
    """
    if text is None:
        return u"Unnamed"
    # Already a unicode string (normal case for .NET System.String in IronPython)
    if isinstance(text, unicode):
        return text.strip()
    # Byte string — decode with a permissive fallback
    if isinstance(text, str):
        try:
            return text.decode("utf-8").strip()
        except (UnicodeDecodeError, AttributeError):
            return text.decode("latin-1").strip()
    # Any other type (.NET object, int, etc.) — convert via unicode()
    try:
        return unicode(text).strip()
    except Exception:
        return u"Unnamed"


def element_id_value(element_id):
    """Get the integer value from an ElementId.

    Revit 2025+ uses .Value (int64), older versions use .IntegerValue (int32).
    Revit 2026 removed .IntegerValue entirely.
    """
    try:
        return int(element_id.Value)
    except AttributeError:
        return int(element_id.IntegerValue)


def get_element_name(element):
    """
    Get the name of a Revit element.
    Useful for both FamilySymbol and other elements.
    """
    try:
        return element.Name
    except AttributeError:
        return DB.Element.Name.__get__(element)


def find_family_symbol_safely(doc, target_family_name, target_type_name=None):
    """
    Safely find a family symbol by name
    """
    try:
        collector = DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol)

        for symbol in collector:
            if symbol.Family.Name == target_family_name:
                if not target_type_name or symbol.Name == target_type_name:
                    return symbol
        return None
    except Exception as e:
        logger.error("Error finding family symbol: %s", str(e))
        return None

# --- Merged from Demolinator/revit-mcp-server (MIT) ---

class _FailureSwallower(DB.IFailuresPreprocessor):
    """Resolve Revit failures during a transaction without ever showing a modal
    dialog. Warnings are deleted (the operation proceeds); if any error-severity
    failure is present, the transaction is rolled back. Either way the headless
    Routes server keeps running instead of hanging on a dialog."""

    def PreprocessFailures(self, failuresAccessor):
        try:
            # Delete all warnings so they don't block (operation continues).
            failuresAccessor.DeleteAllWarnings()
            # If any genuine errors remain, roll back rather than go modal.
            for f in failuresAccessor.GetFailureMessages():
                if f.GetSeverity() == DB.FailureSeverity.Error:
                    return DB.FailureProcessingResult.ProceedWithRollBack
        except Exception:
            pass
        return DB.FailureProcessingResult.Continue



def suppress_warnings(transaction):
    """Configure a transaction so Revit failures never block on a modal dialog.

    Essential for unattended/headless operation: without this, a routine Revit
    warning (e.g. overlapping walls) OR an error (e.g. "Can't cut instance out
    of Wall") pops a modal dialog that blocks the Routes server indefinitely —
    every later request then times out until a human clicks the dialog.

    Warnings are auto-deleted (operation proceeds); errors roll the transaction
    back cleanly. Call right after transaction.Start(). Best-effort — never raises.
    """
    try:
        opts = transaction.GetFailureHandlingOptions()
        opts.SetForcedModalHandling(False)
        opts.SetClearAfterRollback(True)
        opts.SetFailuresPreprocessor(_FailureSwallower())
        transaction.SetFailureHandlingOptions(opts)
    except Exception:
        pass



def sanitize_string(text):
    """Sanitize a string to be ASCII-safe for JSON serialization."""
    if text is None:
        return "Unnamed"
    try:
        return str(text).encode('ascii', 'replace').decode('ascii')
    except Exception:
        return "Unnamed"



def get_element_id_value(element_or_id):
    """
    Extract an integer element ID from an Element or ElementId.
    Accepts both a full Revit Element and a raw ElementId (duck typing).
    Compatible with Revit 2024, 2025, 2026, and 2027.
    Returns a plain Python int for JSON serialization.
    Raises ValueError if the ID cannot be extracted or input is None.
    """
    if element_or_id is None:
        raise ValueError("Cannot extract ElementId from None")
    try:
        eid = element_or_id.Id if hasattr(element_or_id, "Id") else element_or_id
    except Exception:
        raise ValueError("Cannot extract ElementId from input: {}".format(
            type(element_or_id).__name__))
    try:
        return int(eid.Value)
    except (AttributeError, TypeError):
        pass
    try:
        return int(eid.IntegerValue)
    except (AttributeError, TypeError):
        raise ValueError("Cannot read ID value from: {}".format(
            type(element_or_id).__name__))



def make_element_id(id_value):
    """
    Create a DB.ElementId from an integer value.
    Compatible with Revit 2024, 2025, 2026, and 2027.
    Tries System.Int64 constructor first (2024+), falls back to int.
    Raises ValueError if the ElementId cannot be created or input is invalid.
    """
    if id_value is None:
        raise ValueError("Cannot create ElementId from None")
    try:
        int_val = int(id_value)
    except (TypeError, ValueError):
        raise ValueError("Cannot create ElementId from {}: not a valid integer".format(
            repr(id_value)))
    try:
        import System
        return DB.ElementId(System.Int64(int_val))
    except (TypeError, OverflowError, ImportError):
        pass
    try:
        return DB.ElementId(int_val)
    except Exception as e:
        raise ValueError("Cannot create ElementId from {}: {}".format(
            id_value, str(e)))



# --- Merged from ahmedmgamal/mcp-server-for-revit-python-mep (MIT) ---

def mm_to_internal(value_mm):
    """Convert a millimeter value to Revit's internal length units (feet)."""
    try:
        return DB.UnitUtils.ConvertToInternalUnits(
            float(value_mm), DB.UnitTypeId.Millimeters
        )
    except AttributeError:
        # Older Revit API (pre-2021) uses DisplayUnitType instead of UnitTypeId
        return DB.UnitUtils.ConvertToInternalUnits(
            float(value_mm), DB.DisplayUnitType.DUT_MILLIMETERS
        )



def internal_to_mm(value_internal):
    """Convert a Revit internal length value (feet) to millimeters."""
    try:
        return DB.UnitUtils.ConvertFromInternalUnits(
            float(value_internal), DB.UnitTypeId.Millimeters
        )
    except AttributeError:
        return DB.UnitUtils.ConvertFromInternalUnits(
            float(value_internal), DB.DisplayUnitType.DUT_MILLIMETERS
        )



def resolve_category(doc, category_name):
    """
    Find a Revit Category by its display name (case-insensitive).

    Args:
        doc: Revit document
        category_name (str): Display name of the category (e.g. "Ducts", "Pipes")

    Returns:
        DB.Category or None
    """
    if not category_name:
        return None
    try:
        needle = normalize_string(category_name).strip().lower()
        for cat in doc.Settings.Categories:
            try:
                if normalize_string(cat.Name).strip().lower() == needle:
                    return cat
            except Exception:
                continue
        return None
    except Exception as e:
        logger.error("Error resolving category '%s': %s", category_name, str(e))
        return None



def get_connector_manager(element):
    """
    Get the ConnectorManager for an MEP element, whether it is a curve-based
    element (Pipe, Duct, CableTray, Conduit) or a family instance with an
    MEPModel (pumps, VAVs, panels, fixtures, etc.).
    """
    try:
        return element.ConnectorManager
    except AttributeError:
        pass
    try:
        mep_model = element.MEPModel
        if mep_model:
            return mep_model.ConnectorManager
    except AttributeError:
        pass
    return None



def get_unconnected_connectors(element):
    """Return the list of open (unconnected) connectors for an MEP element."""
    connector_manager = get_connector_manager(element)
    if not connector_manager:
        return []

    open_connectors = []
    try:
        for connector in connector_manager.Connectors:
            try:
                if not connector.IsConnected:
                    open_connectors.append(connector)
            except Exception:
                continue
    except Exception as e:
        logger.debug("Error reading connectors: %s", str(e))
    return open_connectors



def connector_origin_dict(connector):
    """Serialize a Connector's origin point to a plain dict of feet coordinates."""
    try:
        origin = connector.Origin
        return {"x": origin.X, "y": origin.Y, "z": origin.Z}
    except Exception:
        return None

