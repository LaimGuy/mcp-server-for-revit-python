# -*- coding: UTF-8 -*-
"""
Generic support/hanger naming for Revit MCP.

Names every element of a category whose name parameter is empty, following a
caller-supplied pattern instead of any hardcoded office convention:

    pattern tokens:  {PREFIX}  {LEVEL}  {NNN}
    default pattern: "{PREFIX}-{LEVEL}-{NNN}"   e.g. SUP-L01-001

- PREFIX comes from `prefix` (fixed string), optionally overridden per element
  by `prefix_map` (case-insensitive family-name keyword -> prefix, first match
  wins).
- LEVEL is read from the element's Reference Level / Level parameter and
  compacted ("Level 01" -> "L01", "LEVEL M1" -> "LM1"). Elements with no level
  read get "L0".
- NNN is a zero-padded sequence per (PREFIX, LEVEL) group. Sequences continue
  from the highest number already present in the model for that group (parsed
  from existing names via the same pattern), so numbers are never reissued.
- Within a group, new elements are ordered by a nearest-neighbour walk from
  the group's last-named element (or the group's min-XY corner if none), so
  numbers follow the physical run the way a hand-numbered set would.

Structure adapted from csamp05/mcp-server-for-revit-python (MIT); all
company-specific conventions (service maps, alias parameters, skip lists,
legacy name formats) removed in favour of request parameters.

NOTE: only DB is imported at module level; `pyrevit.routes` must not be
imported here (breaks under the CPython engine if this module is ever loaded
by a ribbon button). It is imported lazily inside the register function.
"""
import json
import logging
import re

from pyrevit import DB

from .utils import normalize_string, element_id_value, suppress_warnings

logger = logging.getLogger(__name__)

DEFAULT_PATTERN = "{PREFIX}-{LEVEL}-{NNN}"
DEFAULT_NAME_PARAM = "Mark"
DEFAULT_PREFIX = "SUP"
DEFAULT_PAD = 3

LEVEL_PARAM_CANDIDATES = ["Reference Level", "Level", "Schedule Level"]


def _str_param(el, name):
    p = el.LookupParameter(name)
    if p and p.StorageType == DB.StorageType.String:
        v = p.AsString()
        return v if v else u""
    return u""


def _level_token(doc, el):
    """Compact level label for an element: 'Level 01' -> 'L01'."""
    raw = None
    for pn in LEVEL_PARAM_CANDIDATES:
        p = el.LookupParameter(pn)
        if p:
            if p.StorageType == DB.StorageType.ElementId:
                lid = p.AsElementId()
                if lid and lid != DB.ElementId.InvalidElementId:
                    lvl = doc.GetElement(lid)
                    if lvl:
                        raw = normalize_string(getattr(lvl, "Name", None))
                        break
            elif p.StorageType == DB.StorageType.String:
                s = p.AsValueString() or p.AsString()
                if s:
                    raw = normalize_string(s)
                    break
    if not raw:
        try:
            lid = el.LevelId
            if lid and lid != DB.ElementId.InvalidElementId:
                lvl = doc.GetElement(lid)
                if lvl:
                    raw = normalize_string(getattr(lvl, "Name", None))
        except Exception:
            pass
    if not raw:
        return "L0"
    up = raw.strip().upper()
    if up.startswith("LEVEL"):
        rest = re.sub(r"[^A-Z0-9]", "", up[len("LEVEL"):])
        return "L" + (rest or "0")
    compact = re.sub(r"[^A-Z0-9]", "", up)
    if not compact:
        return "L0"
    return compact if compact.startswith("L") else "L" + compact


def _family_name(el):
    try:
        sym = el.Document.GetElement(el.GetTypeId())
        if sym is not None:
            return normalize_string(sym.Family.Name)
    except Exception:
        pass
    return u""


def _prefix_for(el, prefix, prefix_map):
    """Prefix for one element: first prefix_map keyword hit, else `prefix`."""
    if prefix_map:
        fam = _family_name(el).lower()
        for keyword in prefix_map:
            if keyword.lower() in fam:
                return prefix_map[keyword]
    return prefix


def _location_xy(el):
    loc = getattr(el, "Location", None)
    pt = getattr(loc, "Point", None) if loc is not None else None
    if pt is not None:
        return (pt.X, pt.Y)
    try:
        bb = el.get_BoundingBox(None)
        if bb:
            return ((bb.Min.X + bb.Max.X) / 2.0, (bb.Min.Y + bb.Max.Y) / 2.0)
    except Exception:
        pass
    return (0.0, 0.0)


def _pattern_regex(pattern):
    """Compile the naming pattern into a parse regex with named groups."""
    esc = re.escape(pattern)
    esc = esc.replace(re.escape("{PREFIX}"), r"(?P<prefix>[A-Za-z0-9]+)")
    esc = esc.replace(re.escape("{LEVEL}"), r"(?P<level>[A-Z0-9]+)")
    esc = esc.replace(re.escape("{NNN}"), r"(?P<nnn>\d+)")
    return re.compile("^" + esc + "$")


def _walk_order(items, start_xy):
    """Nearest-neighbour ordering of [(el, xy)] starting nearest start_xy."""
    remaining = list(items)
    ordered = []
    cur = start_xy
    while remaining:
        best_i, best_d = 0, None
        for i, (el, xy) in enumerate(remaining):
            d = (xy[0] - cur[0]) ** 2 + (xy[1] - cur[1]) ** 2
            if best_d is None or d < best_d:
                best_i, best_d = i, d
        el, xy = remaining.pop(best_i)
        ordered.append(el)
        cur = xy
    return ordered


def _collect_category(doc, category_name):
    for cat in doc.Settings.Categories:
        if normalize_string(cat.Name) == category_name:
            return list(
                DB.FilteredElementCollector(doc)
                .OfCategoryId(cat.Id)
                .WhereElementIsNotElementType()
                .ToElements()
            )
    return None


def name_supports_impl(doc, data):
    category = data.get("category")
    if not category:
        return {"error": "category is required"}
    name_param = data.get("name_param", DEFAULT_NAME_PARAM)
    pattern = data.get("pattern", DEFAULT_PATTERN)
    prefix = data.get("prefix", DEFAULT_PREFIX)
    prefix_map = data.get("prefix_map") or {}
    pad = int(data.get("pad", DEFAULT_PAD))
    skip_family_keywords = [
        k.lower() for k in (data.get("skip_family_keywords") or [])
    ]
    dry_run = bool(data.get("dry_run", False))

    for token in ("{PREFIX}", "{LEVEL}", "{NNN}"):
        if token not in pattern:
            return {"error": "pattern must contain " + token}

    elements = _collect_category(doc, category)
    if elements is None:
        return {"error": "Category not found: {}".format(category)}
    if not elements:
        return {"error": "No elements in category: {}".format(category)}

    parse_re = _pattern_regex(pattern)

    # Pass 1: existing names -> per-(prefix, level) high-water marks and the
    # location of each group's highest-numbered element (walk start point).
    high = {}
    last_xy = {}
    unnamed = []
    skipped = []
    for el in elements:
        fam_low = _family_name(el).lower()
        hit = None
        for kw in skip_family_keywords:
            if kw in fam_low:
                hit = kw
                break
        if hit is not None:
            skipped.append((el, "family keyword '{}'".format(hit)))
            continue
        current = _str_param(el, name_param).strip()
        if current:
            m = parse_re.match(current)
            if m:
                key = (m.group("prefix").upper(), m.group("level").upper())
                n = int(m.group("nnn"))
                if n > high.get(key, 0):
                    high[key] = n
                    last_xy[key] = _location_xy(el)
            # Named but not matching the pattern: leave untouched.
            continue
        unnamed.append(el)

    # Pass 2: group unnamed by (prefix, level), order by walk, assign.
    groups = {}
    for el in unnamed:
        key = (_prefix_for(el, prefix, prefix_map).upper(),
               _level_token(doc, el))
        groups.setdefault(key, []).append((el, _location_xy(el)))

    plan = []
    for key in sorted(groups.keys()):
        items = groups[key]
        start = last_xy.get(key)
        if start is None:
            start = (min(xy[0] for _, xy in items),
                     min(xy[1] for _, xy in items))
        n = high.get(key, 0)
        for el in _walk_order(items, start):
            n += 1
            new_name = (pattern
                        .replace("{PREFIX}", key[0])
                        .replace("{LEVEL}", key[1])
                        .replace("{NNN}", str(n).zfill(pad)))
            plan.append((el, key, new_name))

    applied = 0
    errors = []
    if not dry_run and plan:
        t = DB.Transaction(doc, "Name supports")
        t.Start()
        suppress_warnings(t)
        try:
            for el, key, new_name in plan:
                p = el.LookupParameter(name_param)
                if p and not p.IsReadOnly:
                    p.Set(new_name)
                    applied += 1
                else:
                    errors.append("{}: no writable '{}' parameter".format(
                        element_id_value(el.Id), name_param))
            t.Commit()
        except Exception as e:
            t.RollBack()
            return {"error": "Transaction failed: {}".format(str(e))}

    group_summary = {}
    for el, key, new_name in plan:
        gk = "{}-{}".format(key[0], key[1])
        g = group_summary.setdefault(
            gk, {"count": 0, "first": new_name, "last": new_name})
        g["count"] += 1
        g["last"] = new_name

    return {
        "status": "success",
        "dry_run": dry_run,
        "category": category,
        "name_param": name_param,
        "pattern": pattern,
        "planned": len(plan),
        "applied": applied,
        "already_named": len(elements) - len(unnamed) - len(skipped),
        "skipped": [
            "{}: {}".format(element_id_value(el.Id), why)
            for el, why in skipped[:25]
        ],
        "groups": group_summary,
        "sample": [name for _, _, name in plan[:10]],
        "errors": errors[:25],
    }


def register_support_naming_routes(api):
    """Register support naming routes (lazy routes import, see module note)."""

    @api.route("/name_supports/", methods=["POST"])
    def name_supports(doc, request):
        try:
            if not request or not request.data:
                return {"error": "No data provided"}
            data = request.data
            if isinstance(data, str):
                data = json.loads(data)
            return name_supports_impl(doc, data)
        except Exception as e:
            logger.error("name_supports failed: %s", str(e))
            return {"error": str(e)}

    logger.info("Support naming routes registered")
