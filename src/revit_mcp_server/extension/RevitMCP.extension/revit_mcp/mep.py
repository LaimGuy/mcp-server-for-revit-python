# -*- coding: UTF-8 -*-
"""
MEP Module for Revit MCP
Handles mechanical, electrical and plumbing tools: linear system creation
(pipes, ducts, cable trays, conduits), connector-based network topology,
and system engineering analysis (panel schedules, clash detection).
"""

from pyrevit import routes, DB
import json
import traceback
import logging

from .utils import (
    normalize_string,
    get_element_name,
    element_id_value,
    mm_to_internal,
    internal_to_mm,
    resolve_category,
    get_connector_manager,
    get_unconnected_connectors,
    connector_origin_dict,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _parse_point(data):
    """Convert a {'x':..,'y':..,'z':..} dict into a DB.XYZ. Raises ValueError."""
    if not data or not all(k in data for k in ("x", "y", "z")):
        raise ValueError("Point must include x, y, z coordinates")
    return DB.XYZ(float(data["x"]), float(data["y"]), float(data["z"]))


def _find_level(doc, level_name, near_point=None):
    """
    Find a Level by name. If no name is given, fall back to the level whose
    elevation is nearest to `near_point.Z`, or the first level found.
    """
    levels = list(
        DB.FilteredElementCollector(doc)
        .OfCategory(DB.BuiltInCategory.OST_Levels)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    if not levels:
        return None

    if level_name:
        for level in levels:
            if get_element_name(level) == level_name:
                return level
        return None

    if near_point is not None:
        return min(levels, key=lambda lvl: abs(lvl.Elevation - near_point.Z))

    return levels[0]


def _find_named_type(doc, revit_class, type_name):
    """
    Find an element of the given class by its name. If type_name is None,
    return the first element found. Returns (element, error_message).
    """
    elements = list(DB.FilteredElementCollector(doc).OfClass(revit_class).ToElements())
    if not elements:
        return None, "No elements of type {} found in the model".format(
            revit_class.__name__
        )

    if not type_name:
        return elements[0], None

    for element in elements:
        try:
            if get_element_name(element) == type_name:
                return element, None
        except Exception:
            continue

    available = sorted(set(get_element_name(e) for e in elements))
    return None, "{} '{}' not found. Available: {}".format(
        revit_class.__name__, type_name, available
    )


def _set_param(element, builtin_param, value, fallback_names=None):
    """
    Set a parameter by BuiltInParameter, falling back to LookupParameter by
    name(s) if the built-in parameter is unavailable on this element/type.
    Returns True if the parameter was set.
    """
    param = None
    try:
        param = element.get_Parameter(builtin_param)
    except Exception:
        param = None

    if (not param or param.IsReadOnly) and fallback_names:
        for name in fallback_names:
            candidate = element.LookupParameter(name)
            if candidate and not candidate.IsReadOnly:
                param = candidate
                break

    if not param or param.IsReadOnly:
        return False

    try:
        param.Set(value)
        return True
    except Exception as e:
        logger.warning("Could not set parameter: %s", str(e))
        return False


def _element_summary(element):
    """Compact {id, name, category} summary for an element."""
    try:
        category_name = element.Category.Name if element.Category else "Unknown"
    except Exception:
        category_name = "Unknown"
    try:
        name = get_element_name(element)
    except Exception:
        name = "Unnamed"
    return {
        "id": element_id_value(element.Id),
        "name": normalize_string(name),
        "category": normalize_string(category_name),
    }


def _create_linear_mep_element(doc, data, config):
    """
    Shared implementation for create_pipe / create_duct / create_cable_tray /
    create_conduit. `config` describes the element-specific bits:

    {
        "create": callable(doc, type_id, system_id_or_None, level_id, start, end) -> element,
        "type_class": DB.<...>Type class,
        "type_param_name": request field name for the type (e.g. "pipe_type_name"),
        "system_class": DB.<...>SystemType class or None,
        "system_param_name": request field name for the system type,
        "size_setter": callable(element, data) -> dict of applied sizes,
    }
    """
    start = _parse_point(data.get("start"))
    end = _parse_point(data.get("end"))
    level = _find_level(doc, data.get("level_name"), near_point=start)
    if not level:
        raise ValueError("No levels found in the model")

    type_element, type_error = _find_named_type(
        doc, config["type_class"], data.get(config["type_param_name"])
    )
    if type_error:
        raise ValueError(type_error)

    system_element = None
    if config.get("system_class"):
        system_element, system_error = _find_named_type(
            doc, config["system_class"], data.get(config["system_param_name"])
        )
        if system_error:
            raise ValueError(system_error)

    t = DB.Transaction(doc, "Create {} via MCP".format(config["label"]))
    t.Start()
    try:
        if system_element is not None:
            new_element = config["create"](
                doc, system_element.Id, type_element.Id, level.Id, start, end
            )
        else:
            new_element = config["create"](doc, type_element.Id, start, end, level.Id)

        applied_sizes = config["size_setter"](new_element, data)

        t.Commit()
    except Exception as tx_error:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise tx_error

    response = {
        "status": "success",
        "element_id": element_id_value(new_element.Id),
        "type_name": normalize_string(get_element_name(type_element)),
        "level": normalize_string(get_element_name(level)),
        "start": {"x": start.X, "y": start.Y, "z": start.Z},
        "end": {"x": end.X, "y": end.Y, "z": end.Z},
        "sizes_applied": applied_sizes,
    }
    if system_element is not None:
        response["system_type"] = normalize_string(get_element_name(system_element))
    return response


def _set_pipe_size(pipe, data):
    applied = {}
    if data.get("diameter_mm") is not None:
        diameter = mm_to_internal(data["diameter_mm"])
        if _set_param(
            pipe, DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM, diameter, ["Diameter"]
        ):
            applied["diameter_mm"] = data["diameter_mm"]
    return applied


def _set_duct_size(duct, data):
    applied = {}
    if data.get("diameter_mm") is not None:
        diameter = mm_to_internal(data["diameter_mm"])
        if _set_param(
            duct,
            DB.BuiltInParameter.RBS_CURVE_DIAMETER_PARAM,
            diameter,
            ["Diameter"],
        ):
            applied["diameter_mm"] = data["diameter_mm"]
    if data.get("width_mm") is not None:
        width = mm_to_internal(data["width_mm"])
        if _set_param(
            duct, DB.BuiltInParameter.RBS_CURVE_WIDTH_PARAM, width, ["Width"]
        ):
            applied["width_mm"] = data["width_mm"]
    if data.get("height_mm") is not None:
        height = mm_to_internal(data["height_mm"])
        if _set_param(
            duct, DB.BuiltInParameter.RBS_CURVE_HEIGHT_PARAM, height, ["Height"]
        ):
            applied["height_mm"] = data["height_mm"]
    return applied


def _set_cable_tray_size(tray, data):
    applied = {}
    if data.get("width_mm") is not None:
        width = mm_to_internal(data["width_mm"])
        if _set_param(
            tray,
            DB.BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM,
            width,
            ["Width"],
        ):
            applied["width_mm"] = data["width_mm"]
    if data.get("height_mm") is not None:
        height = mm_to_internal(data["height_mm"])
        if _set_param(
            tray,
            DB.BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM,
            height,
            ["Height"],
        ):
            applied["height_mm"] = data["height_mm"]
    return applied


def _set_conduit_size(conduit, data):
    applied = {}
    if data.get("diameter_mm") is not None:
        diameter = mm_to_internal(data["diameter_mm"])
        if _set_param(
            conduit,
            DB.BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM,
            diameter,
            ["Diameter"],
        ):
            applied["diameter_mm"] = data["diameter_mm"]
    return applied


def _parse_request_data(request):
    """Parse and validate the JSON body of a POST request."""
    if not request or not request.data:
        raise ValueError("No data provided or invalid request format")
    data = json.loads(request.data) if isinstance(request.data, str) else request.data
    if not data or not isinstance(data, dict):
        raise ValueError("Invalid data format - expected JSON object")
    return data


def register_mep_routes(api):
    """Register all MEP-related routes with the API"""

    # -----------------------------------------------------------------
    # A. Cable Containment & Piping (Linear Systems)
    # -----------------------------------------------------------------

    @api.route("/create_pipe/", methods=["POST"])
    def create_pipe(doc, request):
        """
        Create a pipe run between two points.

        Expected JSON payload:
        {
            "start": {"x": 0.0, "y": 0.0, "z": 0.0},
            "end": {"x": 10.0, "y": 0.0, "z": 0.0},
            "diameter_mm": 100,
            "system_type_name": "Domestic Cold Water",
            "pipe_type_name": "Standard",
            "level_name": "Level 1"
        }
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503
                )
            data = _parse_request_data(request)

            result = _create_linear_mep_element(
                doc,
                data,
                {
                    "label": "Pipe",
                    "create": lambda d, sys_id, type_id, level_id, s, e: DB.Plumbing.Pipe.Create(
                        d, sys_id, type_id, level_id, s, e
                    ),
                    "type_class": DB.Plumbing.PipeType,
                    "type_param_name": "pipe_type_name",
                    "system_class": DB.Plumbing.PipingSystemType,
                    "system_param_name": "system_type_name",
                    "size_setter": _set_pipe_size,
                },
            )
            return routes.make_response(data=result)
        except ValueError as ve:
            return routes.make_response(data={"error": str(ve)}, status=400)
        except Exception as e:
            logger.error("Failed to create pipe: {}".format(str(e)))
            return routes.make_response(
                data={"error": str(e), "traceback": traceback.format_exc()},
                status=500,
            )

    @api.route("/create_sloped_pipe/", methods=["POST"])
    def create_sloped_pipe(doc, request):
        """
        Create a sloped pipe run (drainage / sanitary), applying a slope ratio
        via the Revit API after the pipe is created.

        Expected JSON payload (same as /create_pipe/ plus):
        {
            "slope": 0.01   // e.g. 0.01 for a 1% drop
        }
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503
                )
            data = _parse_request_data(request)
            slope = data.get("slope")
            if slope is None:
                return routes.make_response(
                    data={"error": "slope is required (e.g. 0.01 for a 1% drop)"},
                    status=400,
                )

            start = _parse_point(data.get("start"))
            end = _parse_point(data.get("end"))
            level = _find_level(doc, data.get("level_name"), near_point=start)
            if not level:
                return routes.make_response(
                    data={"error": "No levels found in the model"}, status=404
                )

            pipe_type, type_error = _find_named_type(
                doc, DB.Plumbing.PipeType, data.get("pipe_type_name")
            )
            if type_error:
                return routes.make_response(data={"error": type_error}, status=404)

            system_type, system_error = _find_named_type(
                doc, DB.Plumbing.PipingSystemType, data.get("system_type_name")
            )
            if system_error:
                return routes.make_response(data={"error": system_error}, status=404)

            t = DB.Transaction(doc, "Create Sloped Pipe via MCP")
            t.Start()
            try:
                pipe = DB.Plumbing.Pipe.Create(
                    doc, system_type.Id, pipe_type.Id, level.Id, start, end
                )
                applied_sizes = _set_pipe_size(pipe, data)

                slope_applied = False
                slope_error = None
                try:
                    DB.Plumbing.PlumbingUtils.SetSlope(pipe, float(slope))
                    slope_applied = True
                except Exception as slope_exc:
                    slope_error = str(slope_exc)
                    logger.warning(
                        "Could not apply slope via PlumbingUtils.SetSlope: %s",
                        slope_error,
                    )

                t.Commit()
            except Exception as tx_error:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                raise tx_error

            result = {
                "status": "success",
                "element_id": element_id_value(pipe.Id),
                "type_name": normalize_string(get_element_name(pipe_type)),
                "system_type": normalize_string(get_element_name(system_type)),
                "level": normalize_string(get_element_name(level)),
                "start": {"x": start.X, "y": start.Y, "z": start.Z},
                "end": {"x": end.X, "y": end.Y, "z": end.Z},
                "sizes_applied": applied_sizes,
                "slope_requested": slope,
                "slope_applied": slope_applied,
            }
            if slope_error:
                result["slope_warning"] = (
                    "Slope parameter could not be applied via the API: {}. "
                    "The pipe was created flat; adjust the slope manually if needed."
                ).format(slope_error)

            return routes.make_response(data=result)
        except ValueError as ve:
            return routes.make_response(data={"error": str(ve)}, status=400)
        except Exception as e:
            logger.error("Failed to create sloped pipe: {}".format(str(e)))
            return routes.make_response(
                data={"error": str(e), "traceback": traceback.format_exc()},
                status=500,
            )

    @api.route("/create_duct/", methods=["POST"])
    def create_duct(doc, request):
        """
        Create a duct run between two points.

        Expected JSON payload:
        {
            "start": {"x": 0.0, "y": 0.0, "z": 0.0},
            "end": {"x": 10.0, "y": 0.0, "z": 0.0},
            "width_mm": 400,
            "height_mm": 200,
            "system_type_name": "Supply Air",
            "duct_type_name": "Rectangular",
            "level_name": "Level 1"
        }

        For round ducts, pass "diameter_mm" instead of width_mm/height_mm.
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503
                )
            data = _parse_request_data(request)

            result = _create_linear_mep_element(
                doc,
                data,
                {
                    "label": "Duct",
                    "create": lambda d, sys_id, type_id, level_id, s, e: DB.Mechanical.Duct.Create(
                        d, sys_id, type_id, level_id, s, e
                    ),
                    "type_class": DB.Mechanical.DuctType,
                    "type_param_name": "duct_type_name",
                    "system_class": DB.Mechanical.MechanicalSystemType,
                    "system_param_name": "system_type_name",
                    "size_setter": _set_duct_size,
                },
            )
            return routes.make_response(data=result)
        except ValueError as ve:
            return routes.make_response(data={"error": str(ve)}, status=400)
        except Exception as e:
            logger.error("Failed to create duct: {}".format(str(e)))
            return routes.make_response(
                data={"error": str(e), "traceback": traceback.format_exc()},
                status=500,
            )

    @api.route("/create_cable_tray/", methods=["POST"])
    def create_cable_tray(doc, request):
        """
        Create a cable tray run between two points.

        Expected JSON payload:
        {
            "start": {"x": 0.0, "y": 0.0, "z": 0.0},
            "end": {"x": 10.0, "y": 0.0, "z": 0.0},
            "width_mm": 300,
            "height_mm": 100,
            "cable_tray_type_name": "Cable Tray with Fittings",
            "level_name": "Level 1"
        }
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503
                )
            data = _parse_request_data(request)

            result = _create_linear_mep_element(
                doc,
                data,
                {
                    "label": "Cable Tray",
                    "create": lambda d, type_id, s, e, level_id: DB.Electrical.CableTray.Create(
                        d, type_id, s, e, level_id
                    ),
                    "type_class": DB.Electrical.CableTrayType,
                    "type_param_name": "cable_tray_type_name",
                    "system_class": None,
                    "system_param_name": None,
                    "size_setter": _set_cable_tray_size,
                },
            )
            return routes.make_response(data=result)
        except ValueError as ve:
            return routes.make_response(data={"error": str(ve)}, status=400)
        except Exception as e:
            logger.error("Failed to create cable tray: {}".format(str(e)))
            return routes.make_response(
                data={"error": str(e), "traceback": traceback.format_exc()},
                status=500,
            )

    @api.route("/create_conduit/", methods=["POST"])
    def create_conduit(doc, request):
        """
        Create a conduit run between two points.

        Expected JSON payload:
        {
            "start": {"x": 0.0, "y": 0.0, "z": 0.0},
            "end": {"x": 10.0, "y": 0.0, "z": 0.0},
            "diameter_mm": 25,
            "conduit_type_name": "Rigid Steel Conduit",
            "level_name": "Level 1"
        }
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503
                )
            data = _parse_request_data(request)

            result = _create_linear_mep_element(
                doc,
                data,
                {
                    "label": "Conduit",
                    "create": lambda d, type_id, s, e, level_id: DB.Electrical.Conduit.Create(
                        d, type_id, s, e, level_id
                    ),
                    "type_class": DB.Electrical.ConduitType,
                    "type_param_name": "conduit_type_name",
                    "system_class": None,
                    "system_param_name": None,
                    "size_setter": _set_conduit_size,
                },
            )
            return routes.make_response(data=result)
        except ValueError as ve:
            return routes.make_response(data={"error": str(ve)}, status=400)
        except Exception as e:
            logger.error("Failed to create conduit: {}".format(str(e)))
            return routes.make_response(
                data={"error": str(e), "traceback": traceback.format_exc()},
                status=500,
            )

    # -----------------------------------------------------------------
    # B. Logical Connections & Network Topology
    # -----------------------------------------------------------------

    @api.route("/get_mep_systems/", methods=["POST"])
    def get_mep_systems(doc, request):
        """
        Map the MEP system tree - which elements belong to which piping,
        duct or electrical system, and what equipment serves each system.

        Optional JSON payload:
        {
            "system_type": "piping" | "duct" | "electrical" | "all",  // default "all"
            "name_contains": "AHU-1"                                  // optional filter
        }
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503
                )

            data = {}
            if request and request.data:
                try:
                    data = (
                        json.loads(request.data)
                        if isinstance(request.data, str)
                        else request.data
                    )
                except Exception:
                    data = {}

            system_type = normalize_string(data.get("system_type", "all")).lower()
            name_filter = data.get("name_contains")

            system_classes = {
                "piping": DB.Plumbing.PipingSystem,
                "duct": DB.Mechanical.MechanicalSystem,
                "electrical": DB.Electrical.ElectricalSystem,
            }
            classes_to_query = (
                system_classes.values()
                if system_type == "all"
                else [system_classes.get(system_type)]
            )
            classes_to_query = [c for c in classes_to_query if c is not None]
            if not classes_to_query:
                return routes.make_response(
                    data={
                        "error": "Invalid system_type '{}'. Use one of: piping, duct, electrical, all".format(
                            system_type
                        )
                    },
                    status=400,
                )

            systems_info = []
            for system_class in classes_to_query:
                collector = DB.FilteredElementCollector(doc).OfClass(system_class)
                for system in collector:
                    try:
                        system_name = normalize_string(get_element_name(system))

                        if name_filter and name_filter.lower() not in system_name.lower():
                            continue

                        elements_summary = []
                        try:
                            for member in system.Elements:
                                elements_summary.append(_element_summary(member))
                        except Exception:
                            pass

                        base_equipment = None
                        try:
                            equipment = system.BaseEquipment
                            if equipment:
                                base_equipment = _element_summary(equipment)
                        except Exception:
                            pass

                        systems_info.append(
                            {
                                "id": element_id_value(system.Id),
                                "name": system_name,
                                "system_class": system_class.__name__,
                                "element_count": len(elements_summary),
                                "elements": elements_summary,
                                "base_equipment": base_equipment,
                            }
                        )
                    except Exception as e:
                        logger.warning("Could not process MEP system: %s", str(e))
                        continue

            return routes.make_response(
                data={
                    "status": "success",
                    "systems": systems_info,
                    "system_count": len(systems_info),
                }
            )
        except Exception as e:
            logger.error("Failed to get MEP systems: {}".format(str(e)))
            return routes.make_response(
                data={"error": str(e), "traceback": traceback.format_exc()},
                status=500,
            )

    @api.route("/connect_elements/", methods=["POST"])
    def connect_elements(doc, request):
        """
        Explicitly connect two MEP components using their native Revit
        Connectors, e.g. snapping a pipe to the flow connector on a pump.

        Expected JSON payload:
        {
            "element_id_1": 123456,
            "element_id_2": 654321
        }

        The nearest pair of open, compatible connectors between the two
        elements is used.
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503
                )
            data = _parse_request_data(request)

            id_1 = data.get("element_id_1")
            id_2 = data.get("element_id_2")
            if id_1 is None or id_2 is None:
                return routes.make_response(
                    data={"error": "element_id_1 and element_id_2 are required"},
                    status=400,
                )

            element_1 = doc.GetElement(DB.ElementId(int(id_1)))
            element_2 = doc.GetElement(DB.ElementId(int(id_2)))
            if not element_1 or not element_2:
                return routes.make_response(
                    data={"error": "One or both element ids were not found"},
                    status=404,
                )

            connectors_1 = get_unconnected_connectors(element_1)
            connectors_2 = get_unconnected_connectors(element_2)
            if not connectors_1 or not connectors_2:
                return routes.make_response(
                    data={
                        "error": "One or both elements have no open connectors available"
                    },
                    status=400,
                )

            best_pair = None
            best_distance = None
            for c1 in connectors_1:
                for c2 in connectors_2:
                    try:
                        if c1.Domain != c2.Domain:
                            continue
                        distance = c1.Origin.DistanceTo(c2.Origin)
                    except Exception:
                        continue
                    if best_distance is None or distance < best_distance:
                        best_distance = distance
                        best_pair = (c1, c2)

            if not best_pair:
                return routes.make_response(
                    data={
                        "error": "No compatible open connectors found between the two elements"
                    },
                    status=400,
                )

            t = DB.Transaction(doc, "Connect MEP Elements via MCP")
            t.Start()
            try:
                best_pair[0].ConnectTo(best_pair[1])
                t.Commit()
            except Exception as tx_error:
                if t.HasStarted() and not t.HasEnded():
                    t.RollBack()
                raise tx_error

            return routes.make_response(
                data={
                    "status": "success",
                    "element_id_1": element_id_value(element_1.Id),
                    "element_id_2": element_id_value(element_2.Id),
                    "connector_1_origin": connector_origin_dict(best_pair[0]),
                    "connector_2_origin": connector_origin_dict(best_pair[1]),
                    "distance_between_connectors": best_distance,
                }
            )
        except ValueError as ve:
            return routes.make_response(data={"error": str(ve)}, status=400)
        except Exception as e:
            logger.error("Failed to connect elements: {}".format(str(e)))
            return routes.make_response(
                data={"error": str(e), "traceback": traceback.format_exc()},
                status=500,
            )

    # -----------------------------------------------------------------
    # C. System Engineering Analysis
    # -----------------------------------------------------------------

    @api.route("/read_panel_schedule/", methods=["POST"])
    def read_panel_schedule(doc, request):
        """
        Extract electrical load summary, circuit numbers and phase balance
        for a distribution board (electrical panel).

        Expected JSON payload:
        {
            "panel_name": "Panel A1"
        }
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503
                )
            data = _parse_request_data(request)

            panel_name = data.get("panel_name")
            if not panel_name:
                return routes.make_response(
                    data={"error": "panel_name is required"}, status=400
                )

            panels = (
                DB.FilteredElementCollector(doc)
                .OfCategory(DB.BuiltInCategory.OST_ElectricalEquipment)
                .WhereElementIsNotElementType()
                .ToElements()
            )

            panel = None
            for candidate in panels:
                try:
                    if get_element_name(candidate) == panel_name:
                        panel = candidate
                        break
                except Exception:
                    continue

            if not panel:
                available = sorted(
                    set(
                        normalize_string(get_element_name(p))
                        for p in panels
                    )
                )
                return routes.make_response(
                    data={
                        "error": "Panel '{}' not found".format(panel_name),
                        "available_panels": available[:50],
                    },
                    status=404,
                )

            circuits = (
                DB.FilteredElementCollector(doc)
                .OfClass(DB.Electrical.ElectricalSystem)
                .ToElements()
            )

            circuit_rows = []
            phase_loads = {}
            total_apparent_load = 0.0

            for circuit in circuits:
                try:
                    base_equipment = circuit.BaseEquipment
                    if not base_equipment or base_equipment.Id != panel.Id:
                        continue
                except Exception:
                    continue

                def _param_value(names, builtin=None):
                    if builtin is not None:
                        try:
                            p = circuit.get_Parameter(builtin)
                            if p and p.HasValue:
                                return p.AsValueString() or p.AsDouble()
                        except Exception:
                            pass
                    for name in names:
                        try:
                            p = circuit.LookupParameter(name)
                            if p and p.HasValue:
                                if p.StorageType == DB.StorageType.String:
                                    return p.AsString()
                                return p.AsValueString() or p.AsDouble()
                        except Exception:
                            continue
                    return None

                circuit_number = _param_value(
                    ["Circuit Number"],
                    getattr(DB.BuiltInParameter, "RBS_ELEC_CIRCUIT_NUMBER", None),
                )
                load_name = _param_value(["Load Name"])
                phase = _param_value(
                    ["Electrical Phase", "Phase"],
                    getattr(DB.BuiltInParameter, "RBS_ELEC_CIRCUIT_PHASE_PARAM", None),
                )
                poles = _param_value(
                    ["Number of Poles"],
                    getattr(DB.BuiltInParameter, "RBS_ELEC_NUMBER_OF_POLES", None),
                )
                voltage = _param_value(
                    ["Voltage"], getattr(DB.BuiltInParameter, "RBS_ELEC_VOLTAGE", None)
                )

                apparent_load = None
                try:
                    load_param = circuit.get_Parameter(
                        DB.BuiltInParameter.RBS_ELEC_APPARENT_LOAD_PARAM
                    )
                    if load_param and load_param.HasValue:
                        apparent_load = load_param.AsDouble()
                except Exception:
                    apparent_load = None

                if apparent_load is not None:
                    total_apparent_load += apparent_load
                    phase_key = normalize_string(phase) if phase else "Unknown"
                    phase_loads[phase_key] = phase_loads.get(phase_key, 0.0) + apparent_load

                circuit_rows.append(
                    {
                        "circuit_id": element_id_value(circuit.Id),
                        "circuit_number": circuit_number,
                        "load_name": normalize_string(load_name)
                        if load_name
                        else None,
                        "phase": normalize_string(phase) if phase else None,
                        "poles": poles,
                        "voltage": voltage,
                        "apparent_load": apparent_load,
                    }
                )

            return routes.make_response(
                data={
                    "status": "success",
                    "panel": _element_summary(panel),
                    "circuit_count": len(circuit_rows),
                    "circuits": circuit_rows,
                    "total_apparent_load": total_apparent_load,
                    "phase_balance": phase_loads,
                }
            )
        except ValueError as ve:
            return routes.make_response(data={"error": str(ve)}, status=400)
        except Exception as e:
            logger.error("Failed to read panel schedule: {}".format(str(e)))
            return routes.make_response(
                data={"error": str(e), "traceback": traceback.format_exc()},
                status=500,
            )

    @api.route("/check_clashes/", methods=["POST"])
    def check_clashes(doc, request):
        """
        Run a localized clash detection routine between two categories, e.g.
        Mechanical Ducts vs. Structural Framing, so the AI can self-correct
        routing errors.

        Expected JSON payload:
        {
            "category_a": "Ducts",
            "category_b": "Structural Framing",
            "limit": 25
        }
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active Revit document"}, status=503
                )
            data = _parse_request_data(request)

            category_a_name = data.get("category_a")
            category_b_name = data.get("category_b")
            limit = int(data.get("limit", 25))

            if not category_a_name or not category_b_name:
                return routes.make_response(
                    data={"error": "category_a and category_b are required"},
                    status=400,
                )

            category_a = resolve_category(doc, category_a_name)
            category_b = resolve_category(doc, category_b_name)
            if not category_a or not category_b:
                missing = category_a_name if not category_a else category_b_name
                return routes.make_response(
                    data={"error": "Category '{}' not found".format(missing)},
                    status=404,
                )

            elements_a = (
                DB.FilteredElementCollector(doc)
                .OfCategoryId(category_a.Id)
                .WhereElementIsNotElementType()
                .ToElements()
            )
            elements_b = (
                DB.FilteredElementCollector(doc)
                .OfCategoryId(category_b.Id)
                .WhereElementIsNotElementType()
                .ToElements()
            )

            clashes = []
            checked_pairs = 0
            for element_a in elements_a:
                bbox_a = element_a.get_BoundingBox(None)
                if not bbox_a:
                    continue
                for element_b in elements_b:
                    if len(clashes) >= limit:
                        break
                    bbox_b = element_b.get_BoundingBox(None)
                    if not bbox_b:
                        continue
                    checked_pairs += 1

                    # Quick bounding-box overlap pre-filter
                    if (
                        bbox_a.Min.X > bbox_b.Max.X
                        or bbox_a.Max.X < bbox_b.Min.X
                        or bbox_a.Min.Y > bbox_b.Max.Y
                        or bbox_a.Max.Y < bbox_b.Min.Y
                        or bbox_a.Min.Z > bbox_b.Max.Z
                        or bbox_a.Max.Z < bbox_b.Min.Z
                    ):
                        continue

                    intersection_volume = _solids_intersection_volume(
                        element_a, element_b
                    )
                    if intersection_volume and intersection_volume > 1e-9:
                        clashes.append(
                            {
                                "element_a": _element_summary(element_a),
                                "element_b": _element_summary(element_b),
                                "intersection_volume_ft3": intersection_volume,
                            }
                        )
                if len(clashes) >= limit:
                    break

            return routes.make_response(
                data={
                    "status": "success",
                    "category_a": normalize_string(category_a.Name),
                    "category_b": normalize_string(category_b.Name),
                    "pairs_checked": checked_pairs,
                    "clash_count": len(clashes),
                    "clashes": clashes,
                    "limit_reached": len(clashes) >= limit,
                }
            )
        except ValueError as ve:
            return routes.make_response(data={"error": str(ve)}, status=400)
        except Exception as e:
            logger.error("Failed to check clashes: {}".format(str(e)))
            return routes.make_response(
                data={"error": str(e), "traceback": traceback.format_exc()},
                status=500,
            )

    logger.info("MEP routes registered successfully")


def _solids_intersection_volume(element_a, element_b):
    """
    Compute the intersection volume (in cubic feet) between the solid
    geometry of two elements. Returns 0.0 if they do not intersect or their
    geometry could not be extracted.
    """
    try:
        options = DB.Options()
        options.ComputeReferences = False
        options.DetailLevel = DB.ViewDetailLevel.Fine

        solids_a = _collect_solids(element_a, options)
        solids_b = _collect_solids(element_b, options)

        total_volume = 0.0
        for solid_a in solids_a:
            for solid_b in solids_b:
                try:
                    result = DB.BooleanOperationsUtils.ExecuteBooleanOperation(
                        solid_a, solid_b, DB.BooleanOperationsType.Intersect
                    )
                    if result:
                        total_volume += result.Volume
                except Exception:
                    continue
        return total_volume
    except Exception as e:
        logger.debug("Could not compute solid intersection: %s", str(e))
        return 0.0


def _collect_solids(element, options):
    """Collect non-empty DB.Solid geometry objects from an element."""
    solids = []
    try:
        geometry = element.get_Geometry(options)
        if not geometry:
            return solids
        for geo_object in geometry:
            if isinstance(geo_object, DB.Solid) and geo_object.Volume > 1e-9:
                solids.append(geo_object)
            elif isinstance(geo_object, DB.GeometryInstance):
                instance_geometry = geo_object.GetInstanceGeometry()
                for instance_object in instance_geometry:
                    if (
                        isinstance(instance_object, DB.Solid)
                        and instance_object.Volume > 1e-9
                    ):
                        solids.append(instance_object)
    except Exception as e:
        logger.debug("Could not extract geometry: %s", str(e))
    return solids
