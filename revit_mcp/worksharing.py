# -*- coding: UTF-8 -*-
"""
Worksharing Module for Revit MCP
Worksets, element ownership, reload-latest and relinquish.

Complements document.py, which already covers sync-with-central and
save-as-central. This module adds the workset and ownership layer needed to
work safely in a shared central model.
"""

from pyrevit import routes, revit, DB
import json
import logging

logger = logging.getLogger(__name__)


# Revit 2025+ exposes .Value on id types; older versions use .IntegerValue,
# and 2026 dropped .IntegerValue from ElementId entirely.
def _id_value(some_id):
    try:
        return int(some_id.IntegerValue)
    except AttributeError:
        return int(some_id.Value)


def _safe_name(text):
    from revit_mcp.utils import normalize_string

    return normalize_string(text)


def _checkout_status_name(status):
    if status == DB.CheckoutStatus.OwnedByCurrentUser:
        return "owned_by_you"
    if status == DB.CheckoutStatus.OwnedByOtherUser:
        return "owned_by_other"
    return "not_owned"


def _central_path(doc):
    """User-visible central model path, or None if not workshared."""
    if not doc.IsWorkshared:
        return None
    try:
        model_path = doc.GetWorksharingCentralModelPath()
        if not model_path:
            return None
        return _safe_name(
            DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(model_path)
        )
    except Exception as e:
        logger.warning("Could not resolve central path: {}".format(str(e)))
        return None


def _collect_target_elements(doc, data):
    """Resolve an element set from a request payload.

    Accepts, in priority order: explicit element_ids, a BuiltInCategory name,
    or a workset_id. Returns (elements, description, error_string).
    """
    element_ids = data.get("element_ids") or []
    category = data.get("category")
    workset_id = data.get("workset_id")
    limit = int(data.get("limit", 500))

    if element_ids:
        elements = []
        missing = []
        for raw_id in element_ids[:limit]:
            try:
                el = doc.GetElement(DB.ElementId(int(raw_id)))
                if el:
                    elements.append(el)
                else:
                    missing.append(raw_id)
            except Exception:
                missing.append(raw_id)
        desc = "{} requested element(s)".format(len(element_ids))
        if missing:
            desc += " ({} not found)".format(len(missing))
        return elements, desc, None

    if category:
        bic = getattr(DB.BuiltInCategory, category, None)
        if bic is None:
            return (
                None,
                None,
                "Unknown category '{}'. Use a BuiltInCategory name "
                "such as OST_Walls.".format(category),
            )
        collector = (
            DB.FilteredElementCollector(doc)
            .OfCategory(bic)
            .WhereElementIsNotElementType()
        )
        return list(collector)[:limit], "category {}".format(category), None

    if workset_id is not None:
        ws_filter = DB.ElementWorksetFilter(DB.WorksetId(int(workset_id)))
        collector = (
            DB.FilteredElementCollector(doc)
            .WherePasses(ws_filter)
            .WhereElementIsNotElementType()
        )
        return list(collector)[:limit], "workset {}".format(workset_id), None

    return (
        None,
        None,
        "Provide one of: element_ids, category, or workset_id.",
    )


def register_worksharing_routes(api):
    """Register all worksharing-related routes with the API."""

    @api.route("/worksharing/status/", methods=["GET"])
    def worksharing_status(doc):
        """Overall worksharing state of the active document."""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active document"}, status=400
                )

            doc_title = _safe_name(doc.Title) if doc.Title else "Untitled"

            if not doc.IsWorkshared:
                return routes.make_response(
                    data={
                        "status": "success",
                        "is_workshared": False,
                        "document_title": doc_title,
                        "local_path": _safe_name(doc.PathName),
                        "note": "Document is not workshared. Workset and "
                        "ownership operations do not apply.",
                    }
                )

            central = _central_path(doc)
            local_path = _safe_name(doc.PathName)

            # A central model reports its own path as the central path;
            # a local copy reports a different (server or network) path.
            if central and local_path and central.lower() == local_path.lower():
                model_role = "central"
            elif getattr(doc, "IsDetached", False):
                model_role = "detached"
            else:
                model_role = "local"

            worksets = list(
                DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset)
            )
            owned_by_me = 0
            owned_by_others = 0
            username = _safe_name(doc.Application.Username)
            for ws in worksets:
                owner = _safe_name(ws.Owner)
                if owner and owner == username:
                    owned_by_me += 1
                elif owner and owner != u"Unnamed":
                    owned_by_others += 1

            active_id = None
            active_name = None
            try:
                active_ws_id = doc.GetWorksetTable().GetActiveWorksetId()
                active_id = _id_value(active_ws_id)
                active_ws = doc.GetWorksetTable().GetWorkset(active_ws_id)
                active_name = _safe_name(active_ws.Name)
            except Exception as e:
                logger.warning("Could not read active workset: {}".format(str(e)))

            return routes.make_response(
                data={
                    "status": "success",
                    "is_workshared": True,
                    "document_title": doc_title,
                    "model_role": model_role,
                    "central_path": central,
                    "local_path": local_path,
                    "current_user": username,
                    "active_workset_id": active_id,
                    "active_workset_name": active_name,
                    "user_workset_count": len(worksets),
                    "worksets_owned_by_you": owned_by_me,
                    "worksets_owned_by_others": owned_by_others,
                }
            )

        except Exception as e:
            logger.error("Worksharing status failed: {}".format(str(e)))
            return routes.make_response(
                data={"error": "Worksharing status failed: {}".format(str(e))},
                status=500,
            )

    @api.route("/worksharing/worksets/", methods=["GET"])
    def list_worksets(doc):
        """List user worksets with ownership and open/visible state.

        Deliberately does not count elements per workset: that needs a full
        model iteration and would make this listing slow on large models.
        Use the ownership route with a workset_id to inspect one workset.
        """
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active document"}, status=400
                )
            if not doc.IsWorkshared:
                return routes.make_response(
                    data={"error": "Document is not workshared."}, status=400
                )

            username = _safe_name(doc.Application.Username)
            active_ws_id = None
            try:
                active_ws_id = _id_value(
                    doc.GetWorksetTable().GetActiveWorksetId()
                )
            except Exception:
                pass

            result = []
            for ws in DB.FilteredWorksetCollector(doc).OfKind(
                DB.WorksetKind.UserWorkset
            ):
                owner = _safe_name(ws.Owner)
                ws_id = _id_value(ws.Id)
                entry = {
                    "id": ws_id,
                    "name": _safe_name(ws.Name),
                    "owner": owner if owner and owner != u"Unnamed" else None,
                    "owned_by_you": bool(owner and owner == username),
                    "is_open": bool(ws.IsOpen),
                    "is_editable": bool(ws.IsEditable),
                    "is_visible_by_default": bool(ws.IsVisibleByDefault),
                    "is_active": (ws_id == active_ws_id),
                }
                result.append(entry)

            result.sort(key=lambda w: w["name"])

            return routes.make_response(
                data={
                    "status": "success",
                    "current_user": username,
                    "workset_count": len(result),
                    "worksets": result,
                }
            )

        except Exception as e:
            logger.error("List worksets failed: {}".format(str(e)))
            return routes.make_response(
                data={"error": "List worksets failed: {}".format(str(e))},
                status=500,
            )

    @api.route("/worksharing/ownership/", methods=["POST"])
    def element_ownership(doc, request):
        """Ownership pre-flight for a set of elements.

        Answers "which of these can I actually edit right now" before a bulk
        operation is attempted, so an edit does not fail halfway through.

        Expected payload (one selector required):
        {
            "element_ids": [123, 456],
            "category": "OST_Walls",
            "workset_id": 0,
            "limit": 500,
            "include_details": false
        }
        """
        try:
            data = (
                json.loads(request.data)
                if isinstance(request.data, str)
                else request.data
            ) or {}

            if not doc:
                return routes.make_response(
                    data={"error": "No active document"}, status=400
                )
            if not doc.IsWorkshared:
                return routes.make_response(
                    data={
                        "error": "Document is not workshared; every element "
                        "is editable."
                    },
                    status=400,
                )

            elements, desc, err = _collect_target_elements(doc, data)
            if err:
                return routes.make_response(data={"error": err}, status=400)

            include_details = bool(data.get("include_details", False))
            username = _safe_name(doc.Application.Username)

            buckets = {"owned_by_you": [], "owned_by_other": [], "not_owned": []}
            owners = {}
            details = []

            for el in elements:
                try:
                    status = DB.WorksharingUtils.GetCheckoutStatus(doc, el.Id)
                    key = _checkout_status_name(status)
                    el_id = _id_value(el.Id)
                    buckets[key].append(el_id)

                    if key == "owned_by_other" or include_details:
                        info = DB.WorksharingUtils.GetWorksharingTooltipInfo(
                            doc, el.Id
                        )
                        owner = _safe_name(info.Owner)
                        if key == "owned_by_other":
                            owners[owner] = owners.get(owner, 0) + 1
                        if include_details:
                            details.append(
                                {
                                    "id": el_id,
                                    "status": key,
                                    "owner": owner or None,
                                    "creator": _safe_name(info.Creator) or None,
                                    "last_changed_by": _safe_name(
                                        info.LastChangedBy
                                    )
                                    or None,
                                }
                            )
                except Exception as el_error:
                    logger.warning(
                        "Ownership check failed for an element: {}".format(
                            str(el_error)
                        )
                    )

            blocked = len(buckets["owned_by_other"])
            editable = len(buckets["owned_by_you"]) + len(buckets["not_owned"])

            payload = {
                "status": "success",
                "current_user": username,
                "scope": desc,
                "checked": len(elements),
                "editable_now": editable,
                "blocked_by_others": blocked,
                "safe_to_edit_all": blocked == 0,
                "counts": {
                    "owned_by_you": len(buckets["owned_by_you"]),
                    "not_owned": len(buckets["not_owned"]),
                    "owned_by_other": blocked,
                },
                "blocking_owners": [
                    {"owner": k, "element_count": v}
                    for k, v in sorted(
                        owners.items(), key=lambda kv: -kv[1]
                    )
                ],
                "blocked_element_ids": buckets["owned_by_other"][:100],
            }
            if include_details:
                payload["details"] = details

            return routes.make_response(data=payload)

        except Exception as e:
            logger.error("Ownership check failed: {}".format(str(e)))
            return routes.make_response(
                data={"error": "Ownership check failed: {}".format(str(e))},
                status=500,
            )

    @api.route("/worksharing/set_active_workset/", methods=["POST"])
    def set_active_workset(doc, request):
        """Set the active workset, so newly created elements land correctly.

        Expected payload: {"workset_id": 0} or {"workset_name": "Shell"}
        """
        try:
            data = (
                json.loads(request.data)
                if isinstance(request.data, str)
                else request.data
            ) or {}

            if not doc:
                return routes.make_response(
                    data={"error": "No active document"}, status=400
                )
            if not doc.IsWorkshared:
                return routes.make_response(
                    data={"error": "Document is not workshared."}, status=400
                )

            workset_id = data.get("workset_id")
            workset_name = data.get("workset_name")
            target = None

            for ws in DB.FilteredWorksetCollector(doc).OfKind(
                DB.WorksetKind.UserWorkset
            ):
                if workset_id is not None and _id_value(ws.Id) == int(workset_id):
                    target = ws
                    break
                if workset_name and _safe_name(ws.Name) == workset_name:
                    target = ws
                    break

            if target is None:
                return routes.make_response(
                    data={
                        "error": "Workset not found (id={}, name={}).".format(
                            workset_id, workset_name
                        )
                    },
                    status=404,
                )

            if not target.IsOpen:
                return routes.make_response(
                    data={
                        "error": "Workset '{}' is closed. Open it in Revit "
                        "before making it active.".format(_safe_name(target.Name))
                    },
                    status=400,
                )

            doc.GetWorksetTable().SetActiveWorksetId(target.Id)

            return routes.make_response(
                data={
                    "status": "success",
                    "message": "Active workset set to '{}'.".format(
                        _safe_name(target.Name)
                    ),
                    "workset_id": _id_value(target.Id),
                    "workset_name": _safe_name(target.Name),
                }
            )

        except Exception as e:
            logger.error("Set active workset failed: {}".format(str(e)))
            return routes.make_response(
                data={"error": "Set active workset failed: {}".format(str(e))},
                status=500,
            )

    @api.route("/worksharing/create_workset/", methods=["POST"])
    def create_workset(doc, request):
        """Create a new user workset.

        Expected payload: {"name": "Struct - Braces", "set_active": false}
        """
        try:
            data = (
                json.loads(request.data)
                if isinstance(request.data, str)
                else request.data
            ) or {}

            name = (data.get("name") or "").strip()
            set_active = bool(data.get("set_active", False))

            if not doc:
                return routes.make_response(
                    data={"error": "No active document"}, status=400
                )
            if not doc.IsWorkshared:
                return routes.make_response(
                    data={"error": "Document is not workshared."}, status=400
                )
            if not name:
                return routes.make_response(
                    data={"error": "A workset 'name' is required."}, status=400
                )
            if not DB.WorksetTable.IsWorksetNameUnique(doc, name):
                return routes.make_response(
                    data={
                        "error": "A workset named '{}' already exists.".format(name)
                    },
                    status=400,
                )

            t = DB.Transaction(doc, "Create Workset via MCP")
            t.Start()
            try:
                new_ws = DB.Workset.Create(doc, name)
                if set_active:
                    doc.GetWorksetTable().SetActiveWorksetId(new_ws.Id)
                t.Commit()
            except Exception:
                if t.HasStarted():
                    t.RollBack()
                raise

            return routes.make_response(
                data={
                    "status": "success",
                    "message": "Created workset '{}'.".format(name),
                    "workset_id": _id_value(new_ws.Id),
                    "workset_name": name,
                    "set_active": set_active,
                }
            )

        except Exception as e:
            logger.error("Create workset failed: {}".format(str(e)))
            return routes.make_response(
                data={"error": "Create workset failed: {}".format(str(e))},
                status=500,
            )

    @api.route("/worksharing/move_to_workset/", methods=["POST"])
    def move_to_workset(doc, request):
        """Move elements onto a workset.

        Expected payload (one selector required, plus a destination):
        {
            "element_ids": [123, 456],
            "category": "OST_Walls",
            "target_workset_id": 3,
            "target_workset_name": "Shell"
        }
        """
        try:
            data = (
                json.loads(request.data)
                if isinstance(request.data, str)
                else request.data
            ) or {}

            if not doc:
                return routes.make_response(
                    data={"error": "No active document"}, status=400
                )
            if not doc.IsWorkshared:
                return routes.make_response(
                    data={"error": "Document is not workshared."}, status=400
                )

            target_id = data.get("target_workset_id")
            target_name = data.get("target_workset_name")
            target = None
            for ws in DB.FilteredWorksetCollector(doc).OfKind(
                DB.WorksetKind.UserWorkset
            ):
                if target_id is not None and _id_value(ws.Id) == int(target_id):
                    target = ws
                    break
                if target_name and _safe_name(ws.Name) == target_name:
                    target = ws
                    break
            if target is None:
                return routes.make_response(
                    data={
                        "error": "Target workset not found (id={}, name={}).".format(
                            target_id, target_name
                        )
                    },
                    status=404,
                )

            elements, desc, err = _collect_target_elements(doc, data)
            if err:
                return routes.make_response(data={"error": err}, status=400)

            target_ws_int = _id_value(target.Id)
            moved = 0
            skipped_owned = []
            skipped_pinned = []
            failed = []

            t = DB.Transaction(doc, "Move Elements to Workset via MCP")
            t.Start()
            try:
                for el in elements:
                    try:
                        status = DB.WorksharingUtils.GetCheckoutStatus(doc, el.Id)
                        if status == DB.CheckoutStatus.OwnedByOtherUser:
                            skipped_owned.append(_id_value(el.Id))
                            continue

                        param = el.get_Parameter(
                            DB.BuiltInParameter.ELEM_PARTITION_PARAM
                        )
                        if param is None or param.IsReadOnly:
                            skipped_pinned.append(_id_value(el.Id))
                            continue

                        param.Set(target_ws_int)
                        moved += 1
                    except Exception as el_error:
                        failed.append(
                            {
                                "id": _id_value(el.Id),
                                "error": str(el_error),
                            }
                        )
                t.Commit()
            except Exception:
                if t.HasStarted():
                    t.RollBack()
                raise

            return routes.make_response(
                data={
                    "status": "success",
                    "scope": desc,
                    "target_workset": _safe_name(target.Name),
                    "moved": moved,
                    "skipped_owned_by_others": len(skipped_owned),
                    "skipped_not_assignable": len(skipped_pinned),
                    "failed": len(failed),
                    "blocked_element_ids": skipped_owned[:50],
                    "failures": failed[:20],
                }
            )

        except Exception as e:
            logger.error("Move to workset failed: {}".format(str(e)))
            return routes.make_response(
                data={"error": "Move to workset failed: {}".format(str(e))},
                status=500,
            )

    @api.route("/worksharing/reload_latest/", methods=["POST"])
    def reload_latest(doc, request):
        """Pull the latest changes from central without pushing local edits."""
        try:
            if not doc:
                return routes.make_response(
                    data={"error": "No active document"}, status=400
                )
            if not doc.IsWorkshared:
                return routes.make_response(
                    data={"error": "Document is not workshared."}, status=400
                )

            doc_title = _safe_name(doc.Title) if doc.Title else "Untitled"
            doc.ReloadLatest(DB.ReloadLatestOptions())

            return routes.make_response(
                data={
                    "status": "success",
                    "message": "Reloaded latest from central for '{}'.".format(
                        doc_title
                    ),
                    "document_title": doc_title,
                }
            )

        except Exception as e:
            logger.error("Reload latest failed: {}".format(str(e)))
            return routes.make_response(
                data={"error": "Reload latest failed: {}".format(str(e))},
                status=500,
            )

    @api.route("/worksharing/relinquish/", methods=["POST"])
    def relinquish(doc, request):
        """Release ownership of borrowed elements and worksets.

        Relinquishes without syncing, so teammates are unblocked immediately.
        Note that Revit only releases items with no unsynchronized changes;
        anything still modified locally must be synced first.

        Expected payload (all default true):
        {
            "checked_out_elements": true,
            "user_worksets": true,
            "view_worksets": true,
            "family_worksets": true,
            "standard_worksets": true
        }
        """
        try:
            data = (
                json.loads(request.data)
                if isinstance(request.data, str)
                else request.data
            ) or {}

            if not doc:
                return routes.make_response(
                    data={"error": "No active document"}, status=400
                )
            if not doc.IsWorkshared:
                return routes.make_response(
                    data={"error": "Document is not workshared."}, status=400
                )

            options = DB.RelinquishOptions(False)
            options.CheckedOutElements = bool(
                data.get("checked_out_elements", True)
            )
            options.UserWorksets = bool(data.get("user_worksets", True))
            options.ViewWorksets = bool(data.get("view_worksets", True))
            options.FamilyWorksets = bool(data.get("family_worksets", True))
            options.StandardWorksets = bool(data.get("standard_worksets", True))

            DB.WorksharingUtils.RelinquishOwnership(
                doc, options, DB.TransactWithCentralOptions()
            )

            doc_title = _safe_name(doc.Title) if doc.Title else "Untitled"
            return routes.make_response(
                data={
                    "status": "success",
                    "message": "Relinquished ownership in '{}'. Items with "
                    "unsynchronized changes are retained until you "
                    "sync.".format(doc_title),
                    "document_title": doc_title,
                }
            )

        except Exception as e:
            logger.error("Relinquish failed: {}".format(str(e)))
            return routes.make_response(
                data={"error": "Relinquish failed: {}".format(str(e))},
                status=500,
            )

    logger.info("Worksharing routes registered successfully")
