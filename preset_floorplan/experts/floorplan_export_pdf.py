$extens("include.py")
include("import json", [])
include("import os", [])
include("from pathlib import Path", [])
include("import base64", [])
include("from typing import Any, Dict, List, Optional, Tuple", [])
include("import math", [])
include("import uuid", [])
include("import shapely.geometry", ["extella-pip install shapely"])
include("from shapely.geometry import LineString, Point, Polygon", [])
include("from shapely.ops import unary_union", [])
include("import svgwrite", ["extella-pip install svgwrite"])
include("import cairosvg", ["extella-pip install cairosvg"])
include("import matplotlib", ["extella-pip install matplotlib"])

def floorplan_export_pdf(svg_path: str = "", output_path: str = "") -> dict:
    """fython: первая top-level def до тела floorplan_core."""
    return _floorplan_export_pdf_run(svg_path=svg_path, output_path=output_path)

"""
Каноническая логика пресета планов: валидация, SVG (schematic / technical_bw), PDF∕PNG.
version 1 — схема; version 2 — equipment, annotations, техпрофиль.
"""


import math
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import svgwrite
from shapely.affinity import rotate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from svgwrite.base import BaseElement
from svgwrite.etree import etree as svg_etree

try:
    import cairosvg
except Exception:  # noqa: BLE001
    cairosvg = None  # type: ignore

DEFAULT_PALETTE = [
    "#e8f4f8",
    "#fff4e6",
    "#e8f8e8",
    "#f0e8ff",
    "#fce8ec",
    "#f5f5dc",
]

MAX_PARAMETRIC_OPS = 300


class _SvgFragmentGroup(BaseElement):
    """Вставка сырого XML внутрь <g> (svgwrite не предоставляет Raw в этой версии)."""

    elementname = "g"

    def __init__(self, inner_xml: str, **extra: Any) -> None:
        super().__init__(**extra)
        self._inner_xml = inner_xml.strip()

    def get_xml(self) -> Any:
        xml = svg_etree.Element(self.elementname)
        for attribute, value in sorted(self.attribs.items()):
            if value is not None:
                sval = self.value_to_string(value)
                if sval:
                    xml.set(attribute, sval)
        wrap = f"<root xmlns='http://www.w3.org/2000/svg'>{self._inner_xml}</root>"
        root = svg_etree.fromstring(wrap.encode("utf-8"))
        for child in root:
            xml.append(child)
        return xml


def _units_label(units: str) -> str:
    return {"mm": "mm", "cm": "cm", "m": "m"}.get(units, units)


def _normalize_polygon(ring: List[List[float]]) -> List[Tuple[float, float]]:
    if not ring:
        return []
    pts: List[Tuple[float, float]] = [(float(p[0]), float(p[1])) for p in ring if len(p) >= 2]
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def _bbox_to_polygon(eq: Dict[str, Any]) -> Polygon:
    bb = eq["bbox"]
    x, y = float(bb["x"]), float(bb["y"])
    w, h = float(bb["width"]), float(bb["height"])
    rot = float(bb.get("rotation", 0) or 0)
    r = box(x, y, x + w, y + h)
    if abs(rot) < 1e-6:
        return r
    cx, cy = x + w / 2, y + h / 2
    return rotate(r, rot, origin=(cx, cy))


def _equipment_footprint_geom(eq: Dict[str, Any]) -> Polygon:
    if eq.get("bbox"):
        return _bbox_to_polygon(eq)
    if eq.get("polygon"):
        c = _normalize_polygon(eq["polygon"])
        return Polygon(c)
    raise ValueError("нужен bbox или polygon")


def _validate_parametric_ops(ops: List[Any], prefix: str) -> None:
    if not isinstance(ops, list):
        raise ValueError(f"{prefix}: parametric_symbol должен быть массивом")
    if len(ops) > MAX_PARAMETRIC_OPS:
        raise ValueError(f"{prefix}: слишком много примитивов (>{MAX_PARAMETRIC_OPS})")
    for i, op in enumerate(ops):
        if not isinstance(op, dict) or "op" not in op:
            raise ValueError(f"{prefix}: примитив #{i} без op")
        kind = str(op["op"])
        if kind == "line":
            for k in ("x1", "y1", "x2", "y2"):
                if k not in op:
                    raise ValueError(f"{prefix}: line #{i} без {k}")
        elif kind == "rect":
            for k in ("x", "y", "w", "h"):
                if k not in op:
                    raise ValueError(f"{prefix}: rect #{i} без {k}")
        elif kind == "circle":
            for k in ("cx", "cy", "r"):
                if k not in op:
                    raise ValueError(f"{prefix}: circle #{i} без {k}")
        elif kind == "polyline":
            if "points" not in op or not isinstance(op["points"], list):
                raise ValueError(f"{prefix}: polyline #{i} без points")
        elif kind == "hatch_rect":
            for k in ("x", "y", "w", "h"):
                if k not in op:
                    raise ValueError(f"{prefix}: hatch_rect #{i} без {k}")
        else:
            raise ValueError(f"{prefix}: неизвестный op '{kind}'")


def library_conveyor_linear(w: float, h: float, _: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"op": "rect", "x": 0, "y": 0, "w": w, "h": h, "fill": False},
        {"op": "line", "x1": 0, "y1": h * 0.3, "x2": w, "y2": h * 0.3},
        {"op": "line", "x1": 0, "y1": h * 0.7, "x2": w, "y2": h * 0.7},
    ]


def library_robot_cell(w: float, h: float, _: Dict[str, Any]) -> List[Dict[str, Any]]:
    m = min(w, h) * 0.08
    return [
        {"op": "rect", "x": 0, "y": 0, "w": w, "h": h, "fill": False},
        {
            "op": "rect",
            "x": m,
            "y": m,
            "w": w - 2 * m,
            "h": h - 2 * m,
            "fill": False,
            "dash": "4 3",
        },
        {"op": "circle", "cx": w / 2, "cy": h / 2, "r": min(w, h) * 0.12},
    ]


def library_tank(w: float, h: float, _: Dict[str, Any]) -> List[Dict[str, Any]]:
    r = min(w, h) * 0.35
    cx, cy = w / 2, h / 2
    return [
        {"op": "circle", "cx": cx, "cy": cy, "r": r, "fill": False},
        {"op": "line", "x1": cx - r, "y1": cy, "x2": cx + r, "y2": cy},
        {"op": "line", "x1": cx, "y1": cy - r, "x2": cx, "y2": cy + r},
    ]


def library_workstation(w: float, h: float, _: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"op": "rect", "x": 0, "y": h * 0.35, "w": w * 0.85, "h": h * 0.45, "fill": False},
        {"op": "circle", "cx": w * 0.75, "cy": h * 0.25, "r": min(w, h) * 0.08, "fill": False},
        {"op": "line", "x1": w * 0.75, "y1": h * 0.33, "x2": w * 0.75, "y2": h * 0.35},
    ]


def library_pallet_conveyor(w: float, h: float, _: Dict[str, Any]) -> List[Dict[str, Any]]:
    n = max(3, int(h / max(h * 0.15, 1)))
    ys = [h * (i + 0.5) / n for i in range(n)]
    ops: List[Dict[str, Any]] = [{"op": "rect", "x": 0, "y": 0, "w": w, "h": h, "fill": False}]
    for yy in ys:
        ops.append({"op": "line", "x1": w * 0.15, "y1": yy, "x2": w * 0.85, "y2": yy})
    return ops


def library_packing_block(w: float, h: float, _: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"op": "rect", "x": 0, "y": 0, "w": w, "h": h, "fill": False},
        {"op": "line", "x1": w * 0.33, "y1": 0, "x2": w * 0.33, "y2": h},
        {"op": "line", "x1": w * 0.66, "y1": 0, "x2": w * 0.66, "y2": h},
    ]


def library_stretch_wrapper(w: float, h: float, _: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"op": "rect", "x": 0, "y": 0, "w": w, "h": h, "fill": False},
        {"op": "rect", "x": w * 0.2, "y": h * 0.25, "w": w * 0.6, "h": h * 0.5, "fill": False},
        {"op": "line", "x1": 0, "y1": h * 0.5, "x2": w * 0.2, "y2": h * 0.5},
        {"op": "line", "x1": w * 0.8, "y1": h * 0.5, "x2": w, "y2": h * 0.5},
    ]


def library_generic(w: float, h: float, _: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"op": "rect", "x": 0, "y": 0, "w": w, "h": h, "fill": False, "dash": "6 4"}]


LIBRARY: Dict[str, Callable[[float, float, Dict[str, Any]], List[Dict[str, Any]]]] = {
    "conveyor_linear": library_conveyor_linear,
    "robot_cell": library_robot_cell,
    "tank": library_tank,
    "workstation": library_workstation,
    "pallet_conveyor": library_pallet_conveyor,
    "packing_block": library_packing_block,
    "stretch_wrapper": library_stretch_wrapper,
    "generic": library_generic,
}


def validate_and_normalize(spec: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    ver = spec.get("version")
    if ver not in (1, 2):
        raise ValueError("unsupported_version: ожидается version == 1 или 2")

    units = spec.get("units")
    if units not in ("mm", "cm", "m"):
        raise ValueError("invalid_units: ожидается mm | cm | m")

    rooms_in = spec.get("rooms") or []
    if not isinstance(rooms_in, list) or not rooms_in:
        raise ValueError("rooms_required: нужна минимум одна комната")

    rooms_out: List[Dict[str, Any]] = []
    for idx, room in enumerate(rooms_in):
        if not isinstance(room, dict):
            raise ValueError(f"room_invalid: комната #{idx} не объект")
        rid = str(room.get("id", f"room_{idx}"))
        name = str(room.get("name", rid))
        zt = room.get("zone_type", "other")
        if zt not in ("production", "storage", "other"):
            raise ValueError(f"room '{rid}': zone_type production|storage|other")
        poly = room.get("polygon")
        if not isinstance(poly, list) or len(poly) < 3:
            raise ValueError(f"invalid_polygon: комната '{rid}' — меньше 3 точек")
        coords = _normalize_polygon(poly)
        if len(coords) < 3:
            raise ValueError(f"invalid_polygon: комната '{rid}' после нормализации < 3 точек")
        try:
            sh_poly = Polygon(coords)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"invalid_polygon: комната '{rid}' — {e}") from e
        if not sh_poly.is_valid:
            reason = sh_poly.is_valid_reason if hasattr(sh_poly, "is_valid_reason") else "invalid"
            raise ValueError(f"invalid_polygon: комната '{rid}' — {reason}")
        if sh_poly.area <= 0:
            raise ValueError(f"invalid_polygon: комната '{rid}' — нулевая площадь")
        rooms_out.append(
            {
                "id": rid,
                "name": name,
                "zone_type": zt,
                "polygon": [list(p) for p in coords],
                "_geom": sh_poly,
            }
        )

    walls_out: List[Dict[str, Any]] = []
    for w in spec.get("walls") or []:
        if not isinstance(w, dict):
            continue
        try:
            thickness = float(w.get("thickness", spec.get("style", {}).get("wall_thickness", 8)))
        except (TypeError, ValueError):
            thickness = 8.0
        walls_out.append(
            {
                "id": str(w.get("id", "")),
                "x1": float(w["x1"]),
                "y1": float(w["y1"]),
                "x2": float(w["x2"]),
                "y2": float(w["y2"]),
                "thickness": max(thickness, 0.0),
            }
        )

    equipment_out: List[Dict[str, Any]] = []
    if ver == 1 and spec.get("equipment"):
        warnings.append("equipment_ignored_requires_version_2")
    elif ver == 2 and spec.get("equipment"):
        seen_ids = set()
        for ei, eq in enumerate(spec["equipment"]):
            if not isinstance(eq, dict):
                raise ValueError(f"equipment #{ei} не объект")
            eid = str(eq.get("id", f"eq_{ei}"))
            if eid in seen_ids:
                raise ValueError(f"equipment: дубликат id '{eid}'")
            seen_ids.add(eid)
            label = str(eq.get("label", eid))
            try:
                fp = _equipment_footprint_geom({**eq, "id": eid})
            except (KeyError, ValueError) as e:
                raise ValueError(f"equipment '{eid}': {e}") from e
            rep = eq.get("representation") or {}
            if not isinstance(rep, dict):
                raise ValueError(f"equipment '{eid}': representation объектом")
            if rep.get("parametric_symbol"):
                _validate_parametric_ops(rep["parametric_symbol"], f"equipment '{eid}'")
            if rep.get("external_svg"):
                ex = rep["external_svg"]
                if not isinstance(ex, dict):
                    raise ValueError(f"equipment '{eid}': external_svg объектом")
                if ex.get("fragment"):
                    if len(str(ex["fragment"])) > 500_000:
                        raise ValueError(f"equipment '{eid}': слишком большой fragment")
                elif ex.get("path"):
                    p = Path(str(ex["path"])).expanduser()
                    if not p.is_file():
                        warnings.append(f"equipment '{eid}': external_svg path не найден: {p}")
            if rep.get("external_raster"):
                er = rep["external_raster"]
                if not isinstance(er, dict):
                    raise ValueError(f"equipment '{eid}': external_raster объектом")
                if er.get("data_uri") and len(str(er["data_uri"])) > 2_000_000:
                    raise ValueError(f"equipment '{eid}': слишком большой data_uri")
                elif er.get("path"):
                    p = Path(str(er["path"])).expanduser()
                    if not p.is_file():
                        warnings.append(f"equipment '{eid}': external_raster path не найден: {p}")
            equipment_out.append(
                {
                    "id": eid,
                    "label": label,
                    "z_index": float(eq.get("z_index", 0)),
                    "footprint_only": bool(eq.get("footprint_only", False)),
                    "bbox": dict(eq["bbox"]) if eq.get("bbox") else None,
                    "polygon": _normalize_polygon(eq["polygon"]) if eq.get("polygon") else None,
                    "representation": rep,
                    "_footprint": fp,
                }
            )

    annotations_out: Dict[str, Any] = {}
    if spec.get("annotations"):
        if ver == 1:
            warnings.append("annotations_ignored_requires_version_2")
        elif ver == 2:
            ann = spec["annotations"]
            if isinstance(ann, dict) and ann.get("callouts"):
                for ci, call in enumerate(ann["callouts"]):
                    if not isinstance(call, dict):
                        raise ValueError(f"callout #{ci} не объект")
                    if "id" not in call or "text" not in call:
                        raise ValueError(f"callout #{ci}: нужны id и text")
                    if call.get("anchor") is not None:
                        anch = call["anchor"]
                        if not isinstance(anch, dict):
                            raise ValueError(f"callout #{ci}: anchor объектом с полями x, y")
                        if "x" not in anch or "y" not in anch:
                            raise ValueError(f"callout #{ci}: у anchor нужны x и y")
                annotations_out = dict(ann)

    style = dict(spec.get("style") or {})
    profile = str(style.get("render_profile", "schematic"))
    if profile not in ("schematic", "technical_bw"):
        raise ValueError("style.render_profile: schematic | technical_bw")

    normalized: Dict[str, Any] = {
        "version": ver,
        "units": units,
        "title": str(spec.get("title") or "Floor plan"),
        "metadata": dict(spec.get("metadata") or {}),
        "rooms": rooms_out,
        "walls": walls_out,
        "openings": list(spec.get("openings") or []),
        "equipment": equipment_out,
        "annotations": annotations_out,
        "style": style,
    }
    return normalized, warnings


def _room_geom(room: Dict[str, Any]) -> Polygon:
    if "_geom" in room:
        return room["_geom"]
    coords = _normalize_polygon(room["polygon"])
    return Polygon(coords)


def _bounds(normalized: Dict[str, Any]) -> Tuple[float, float, float, float]:
    geoms: List[Any] = []
    for r in normalized["rooms"]:
        geoms.append(_room_geom(r))
    for w in normalized["walls"]:
        t = max(w["thickness"], 0.5)
        geoms.append(
            LineString([(w["x1"], w["y1"]), (w["x2"], w["y2"])]).buffer(
                t / 2.0, cap_style=2, join_style=2
            )
        )
    for eq in normalized.get("equipment") or []:
        if eq.get("_footprint") is not None:
            geoms.append(eq["_footprint"])
    if not geoms:
        return 0.0, 0.0, 100.0, 100.0
    u = unary_union(geoms)
    minx, miny, maxx, maxy = u.bounds
    return float(minx), float(miny), float(maxx), float(maxy)


def _external_raster_href(rep: Dict[str, Any]) -> Optional[str]:
    """file:// или data: URI для SVG image href; None если нет валидного источника."""
    er = rep.get("external_raster")
    if not isinstance(er, dict):
        return None
    if er.get("data_uri"):
        s = str(er["data_uri"]).strip()
        if s.startswith("data:") and len(s) < 2_500_000:
            return s
    if er.get("path"):
        p = Path(str(er["path"])).expanduser()
        if p.is_file():
            return p.resolve().as_uri()
    return None


def _equipment_transform(eq: Dict[str, Any]) -> Tuple[float, float, float, float, float]:
    if eq.get("bbox"):
        bb = eq["bbox"]
        x, y = float(bb["x"]), float(bb["y"])
        w, h = float(bb["width"]), float(bb["height"])
        rot = float(bb.get("rotation", 0) or 0)
        return x, y, w, h, rot
    b = eq["_footprint"].bounds
    x0, y0, x1, y1 = b
    return float(x0), float(y0), float(x1 - x0), float(y1 - y0), 0.0


def _resolve_ops(eq: Dict[str, Any], w: float, h: float) -> List[Dict[str, Any]]:
    if eq.get("footprint_only"):
        return library_generic(w, h, {})
    rep = eq.get("representation") or {}
    if _external_raster_href(rep):
        return []
    if rep.get("parametric_symbol"):
        return list(rep["parametric_symbol"])
    key = str(rep.get("library_key") or "generic")
    params = dict(rep.get("library_params") or {})
    fn = LIBRARY.get(key, library_generic)
    return fn(w, h, params)


def _apply_op(
    dwg: svgwrite.Drawing,
    parent: Any,
    op: Dict[str, Any],
    eq_stroke: float,
    pattern_url: Optional[str],
) -> None:
    opname = str(op["op"])
    dash_kw: Dict[str, Any] = {}
    if op.get("dash"):
        dash_kw["stroke_dasharray"] = str(op["dash"])
    if opname == "line":
        parent.add(
            dwg.line(
                start=(float(op["x1"]), float(op["y1"])),
                end=(float(op["x2"]), float(op["y2"])),
                stroke="#111111",
                stroke_width=eq_stroke,
                fill="none",
                **dash_kw,
            )
        )
    elif opname == "rect":
        fill = "none" if not op.get("fill") else "#cccccc"
        parent.add(
            dwg.rect(
                insert=(float(op["x"]), float(op["y"])),
                size=(float(op["w"]), float(op["h"])),
                stroke="#111111",
                stroke_width=eq_stroke,
                fill=fill,
                **dash_kw,
            )
        )
    elif opname == "circle":
        parent.add(
            dwg.circle(
                center=(float(op["cx"]), float(op["cy"])),
                r=float(op["r"]),
                stroke="#111111",
                stroke_width=eq_stroke,
                fill="none",
                **dash_kw,
            )
        )
    elif opname == "polyline":
        pts = [(float(p[0]), float(p[1])) for p in op["points"]]
        parent.add(
            dwg.polyline(
                points=pts,
                stroke="#111111",
                stroke_width=eq_stroke,
                fill="none",
                **dash_kw,
            )
        )
    elif opname == "hatch_rect":
        pu = pattern_url or "#eeeeee"
        parent.add(
            dwg.rect(
                insert=(float(op["x"]), float(op["y"])),
                size=(float(op["w"]), float(op["h"])),
                fill=pu,
                stroke="#333333",
                stroke_width=max(0.3, eq_stroke * 0.5),
            )
        )


def _add_defs_hatch(dwg: svgwrite.Drawing, pattern_id: str, spacing: float = 6) -> None:
    pat = dwg.pattern(
        size=(spacing, spacing),
        patternUnits="userSpaceOnUse",
        id=pattern_id,
        patternTransform=f"rotate(45 {spacing / 2} {spacing / 2})",
    )
    pat.add(dwg.line(start=(0, 0), end=(0, spacing), stroke="#555555", stroke_width=0.6))
    dwg.defs.add(pat)


def spec_to_svg(normalized: Dict[str, Any], margin_ratio: float = 0.08) -> str:
    profile = str(normalized.get("style", {}).get("render_profile", "schematic"))
    if profile == "technical_bw":
        return _spec_to_svg_technical(normalized, margin_ratio)
    return _spec_to_svg_schematic(normalized, margin_ratio)


def _draw_scale_bar_title(
    dwg: svgwrite.Drawing,
    normalized: Dict[str, Any],
    vb_x0: float,
    vb_y0: float,
    vb_w: float,
    vb_h: float,
    margin: float,
    dx: float,
    dy: float,
    wall_stroke: float,
) -> None:
    scale_len = max(dx, dy) * 0.08
    sx0 = vb_x0 + vb_w * 0.05
    sy0 = vb_y0 + vb_h * 0.92
    dwg.add(
        dwg.line(
            start=(sx0, sy0),
            end=(sx0 + scale_len, sy0),
            stroke="#000000",
            stroke_width=wall_stroke,
        )
    )
    ulabel = _units_label(normalized["units"])
    dwg.add(
        dwg.text(
            f"{scale_len:.0f} {ulabel}",
            insert=(sx0 + scale_len / 2, sy0 - max(dx, dy) * 0.02),
            text_anchor="middle",
            fill="#000000",
            font_size=max(dx, dy) * 0.02,
            font_family="sans-serif",
        )
    )
    dwg.add(
        dwg.text(
            normalized["title"],
            insert=(vb_x0 + vb_w / 2, vb_y0 + margin * 0.4),
            text_anchor="middle",
            fill="#000000",
            font_size=max(dx, dy) * 0.04,
            font_family="sans-serif",
            font_weight="bold",
        )
    )


def _spec_to_svg_schematic(normalized: Dict[str, Any], margin_ratio: float) -> str:
    minx, miny, maxx, maxy = _bounds(normalized)
    dx = maxx - minx or 1.0
    dy = maxy - miny or 1.0
    margin = margin_ratio * max(dx, dy)
    vb_x0 = minx - margin
    vb_y0 = miny - margin
    vb_w = dx + 2 * margin
    vb_h = dy + 2 * margin

    dwg = svgwrite.Drawing(size=(f"{vb_w:.4f}", f"{vb_h:.4f}"), viewBox=f"{vb_x0:.4f} {vb_y0:.4f} {vb_w:.4f} {vb_h:.4f}")
    dwg.attribs["xmlns"] = "http://www.w3.org/2000/svg"

    style = normalized.get("style") or {}
    show_grid = bool(style.get("show_grid", False))
    grid_step = float(style.get("grid_step", max(dx, dy) / 20 or 10))
    palette = list(style.get("room_palette") or DEFAULT_PALETTE)
    wall_stroke = float(style.get("wall_stroke_mm", max(dx, dy) / 400 + 1))

    dwg.add(dwg.rect(insert=(vb_x0, vb_y0), size=(vb_w, vb_h), fill="white", stroke="none"))

    if show_grid and grid_step > 0:
        grid_g = dwg.add(dwg.g(id="grid", stroke="#eeeeee", stroke_width=wall_stroke * 0.3))
        gx = math.floor(vb_x0 / grid_step) * grid_step
        while gx <= vb_x0 + vb_w:
            grid_g.add(dwg.line(start=(gx, vb_y0), end=(gx, vb_y0 + vb_h)))
            gx += grid_step
        gy = math.floor(vb_y0 / grid_step) * grid_step
        while gy <= vb_y0 + vb_h:
            grid_g.add(dwg.line(start=(vb_x0, gy), end=(vb_x0 + vb_w, gy)))
            gy += grid_step

    for i, room in enumerate(normalized["rooms"]):
        poly = room["_geom"]
        exterior = list(poly.exterior.coords)
        fill = palette[i % len(palette)]
        pts = [(x, y) for x, y in exterior]
        dwg.add(
            dwg.polygon(
                points=pts,
                fill=fill,
                stroke="#222222",
                stroke_width=wall_stroke,
                fill_opacity=0.9,
            )
        )
        c = poly.centroid
        if isinstance(c, Point) and not c.is_empty:
            dwg.add(
                dwg.text(
                    room["name"],
                    insert=(float(c.x), float(c.y)),
                    text_anchor="middle",
                    dominant_baseline="middle",
                    fill="#111111",
                    font_size=max(dx, dy) * 0.025,
                    font_family="sans-serif",
                )
            )

    for wi, w in enumerate(normalized["walls"]):
        ls = LineString([(w["x1"], w["y1"]), (w["x2"], w["y2"])])
        thick = max(w["thickness"], 0.5)
        wall_poly = ls.buffer(thick / 2.0, cap_style=2, join_style=2)
        ext = [(x, y) for x, y in wall_poly.exterior.coords]
        wid = w["id"] if str(w.get("id", "")).strip() else f"w{wi}"
        patch = dwg.add(dwg.g(id=f"wall_{wid}"))
        patch.add(
            dwg.polygon(
                points=ext,
                fill="#333333",
                stroke="#111111",
                stroke_width=wall_stroke * 0.5,
            )
        )

    if normalized.get("equipment"):
        sorted_eq = sorted(normalized["equipment"], key=lambda e: e.get("z_index", 0))
        eq_layer = dwg.add(dwg.g(id="equipment_schematic"))
        ref = max(dx, dy)
        for eq in sorted_eq:
            fp = eq["_footprint"]
            ext = [(float(x), float(y)) for x, y in fp.exterior.coords]
            eq_layer.add(
                dwg.polygon(
                    points=ext,
                    fill="none",
                    stroke="#333333",
                    stroke_width=max(0.5, wall_stroke * 0.4),
                    stroke_dasharray="6 4",
                )
            )
            cen = fp.centroid
            if isinstance(cen, Point) and not cen.is_empty:
                eq_layer.add(
                    dwg.text(
                        eq["label"],
                        insert=(float(cen.x), float(cen.y)),
                        text_anchor="middle",
                        dominant_baseline="middle",
                        fill="#111111",
                        font_size=ref * 0.022,
                        font_family="sans-serif",
                    )
                )
        _embed_external_svg_layer(dwg, sorted_eq)
        _embed_external_raster_layer(dwg, sorted_eq)
        _draw_callouts(dwg, normalized, ref)

    _draw_scale_bar_title(dwg, normalized, vb_x0, vb_y0, vb_w, vb_h, margin, dx, dy, wall_stroke)
    return dwg.tostring()


def _add_coord_labels(
    dwg: svgwrite.Drawing,
    vb_x0: float,
    vb_y0: float,
    vb_w: float,
    vb_h: float,
    step: float,
    ref: float,
) -> None:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    gx0 = math.ceil(vb_x0 / step) * step
    col = 0
    gx = gx0
    fs = max(ref * 0.015, 8)
    while gx <= vb_x0 + vb_w - 1e-6:
        letter = letters[col % len(letters)]
        dwg.add(
            dwg.text(
                letter,
                insert=(gx, vb_y0 + vb_h - fs * 0.3),
                text_anchor="middle",
                fill="#333333",
                font_size=fs,
                font_family="sans-serif",
            )
        )
        gx += step
        col += 1
    gy0 = math.ceil(vb_y0 / step) * step
    row = 1
    gy = gy0
    while gy <= vb_y0 + vb_h - 1e-6:
        dwg.add(
            dwg.text(
                str(row),
                insert=(vb_x0 + fs * 0.4, gy),
                text_anchor="middle",
                dominant_baseline="middle",
                fill="#333333",
                font_size=fs,
                font_family="sans-serif",
            )
        )
        gy += step
        row += 1


def _parse_svg_fragment(content: str) -> Optional[_SvgFragmentGroup]:
    s = content.strip()
    if not s.startswith("<"):
        return None
    try:
        root = ET.fromstring(s.encode("utf-8"))
        tag = root.tag.split("}")[-1]
        if tag == "svg":
            inner_parts = []
            for c in list(root):
                inner_parts.append(ET.tostring(c, encoding="unicode"))
            inner = "".join(inner_parts)
            if not inner:
                return None
            return _SvgFragmentGroup(inner)
        return _SvgFragmentGroup(ET.tostring(root, encoding="unicode"))
    except Exception:
        m = re.search(r"<g[\s>][\s\S]*?</g>", s, re.I)
        if m:
            try:
                return _SvgFragmentGroup(m.group(0))
            except Exception:
                return None
        return None


def _embed_external_svg_layer(dwg: svgwrite.Drawing, equipment: List[Dict[str, Any]]) -> None:
    g0 = dwg.add(dwg.g(id="external_svg_symbols"))
    for eq in equipment:
        rep = eq.get("representation") or {}
        ex = rep.get("external_svg")
        if not isinstance(ex, dict):
            continue
        content = ""
        if ex.get("fragment"):
            content = str(ex["fragment"])
        elif ex.get("path"):
            p = Path(str(ex["path"])).expanduser()
            if p.is_file():
                content = p.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            continue
        inner_xml = _parse_svg_fragment(content)
        if inner_xml is None:
            continue
        x0, y0, lw, lh, rot = _equipment_transform(eq)
        cx, cy = x0 + lw / 2, y0 + lh / 2
        sub = dwg.g(
            transform=f"translate({cx:.4f},{cy:.4f}) rotate({-rot:.4f}) translate({-lw / 2:.4f},{-lh / 2:.4f})"
        )
        sub.add(inner_xml)
        g0.add(sub)


def _embed_external_raster_layer(dwg: svgwrite.Drawing, equipment: List[Dict[str, Any]]) -> None:
    g0 = dwg.add(dwg.g(id="external_raster_symbols"))
    for eq in equipment:
        rep = eq.get("representation") or {}
        href = _external_raster_href(rep)
        if not href:
            continue
        x0, y0, lw, lh, rot = _equipment_transform(eq)
        cx, cy = x0 + lw / 2, y0 + lh / 2
        sub = dwg.g(
            transform=f"translate({cx:.4f},{cy:.4f}) rotate({-rot:.4f}) translate({-lw / 2:.4f},{-lh / 2:.4f})"
        )
        sub.add(
            dwg.image(
                href=href,
                insert=(0, 0),
                size=(lw, lh),
                preserveAspectRatio="xMidYMid meet",
            )
        )
        g0.add(sub)


def _draw_callouts(dwg: svgwrite.Drawing, normalized: Dict[str, Any], ref_size: float) -> None:
    ann = normalized.get("annotations") or {}
    calls = ann.get("callouts") or []
    if not calls:
        return
    eq_by_id = {e["id"]: e for e in normalized.get("equipment") or []}
    fs = max(ref_size * 0.016, 9)
    r = fs * 0.55
    for c in calls:
        off = c.get("offset") or {}
        ox, oy = float(off.get("dx", 30)), float(off.get("dy", -25))
        tid = c.get("target_id")
        ax = ay = None
        if tid and tid in eq_by_id:
            cen = eq_by_id[tid]["_footprint"].centroid
            if isinstance(cen, Point) and not cen.is_empty:
                ax, ay = float(cen.x), float(cen.y)
        elif c.get("anchor"):
            anch = c["anchor"]
            if not isinstance(anch, dict) or "x" not in anch or "y" not in anch:
                continue
            ax = float(anch["x"])
            ay = float(anch["y"])
        if ax is None:
            continue
        lx, ly = ax + ox, ay + oy
        dwg.add(dwg.line(start=(ax, ay), end=(lx, ly), stroke="#111111", stroke_width=max(0.5, ref_size / 500)))
        dwg.add(dwg.circle(center=(lx, ly), r=r, fill="white", stroke="#111111", stroke_width=0.8))
        dwg.add(
            dwg.text(
                str(c["id"]),
                insert=(lx, ly),
                text_anchor="middle",
                dominant_baseline="middle",
                font_size=fs * 0.7,
                font_family="sans-serif",
            )
        )
        dwg.add(
            dwg.text(
                str(c["text"]),
                insert=(lx + r + 6, ly),
                dominant_baseline="middle",
                font_size=fs * 0.55,
                font_family="sans-serif",
            )
        )


def _spec_to_svg_technical(normalized: Dict[str, Any], margin_ratio: float) -> str:
    minx, miny, maxx, maxy = _bounds(normalized)
    dx = maxx - minx or 1.0
    dy = maxy - miny or 1.0
    margin = margin_ratio * max(dx, dy)
    vb_x0 = minx - margin
    vb_y0 = miny - margin
    vb_w = dx + 2 * margin
    vb_h = dy + 2 * margin

    dwg = svgwrite.Drawing(size=(f"{vb_w:.4f}", f"{vb_h:.4f}"), viewBox=f"{vb_x0:.4f} {vb_y0:.4f} {vb_w:.4f} {vb_h:.4f}")
    dwg.attribs["xmlns"] = "http://www.w3.org/2000/svg"

    style = normalized.get("style") or {}
    tech = dict(style.get("technical") or {})
    wall_stroke = float(tech.get("wall_stroke", max(dx, dy) / 250 + 1.5))
    eq_stroke = float(tech.get("equipment_stroke", max(dx, dy) / 500 + 0.8))
    room_outline = float(tech.get("room_outline_stroke", wall_stroke * 0.6))
    grid_major = float(tech.get("grid_major_stroke", max(dx, dy) / 600 + 0.4))
    room_fill = str(tech.get("room_fill_technical", "#fafafa"))
    hatch_storage = bool(tech.get("hatch_storage", True))

    hatch_id = "diagHatch"
    _add_defs_hatch(dwg, hatch_id, spacing=max(4.0, min(dx, dy) / 80))

    dwg.add(dwg.rect(insert=(vb_x0, vb_y0), size=(vb_w, vb_h), fill="white", stroke="none"))

    show_grid = bool(style.get("show_grid", True))
    grid_step = float(style.get("grid_step", max(dx, dy) / 24 or 10))
    if show_grid and grid_step > 0:
        grid_g = dwg.add(dwg.g(id="grid_minor", stroke="#dddddd", stroke_width=grid_major * 0.6))
        gx = math.floor(vb_x0 / grid_step) * grid_step
        while gx <= vb_x0 + vb_w:
            grid_g.add(dwg.line(start=(gx, vb_y0), end=(gx, vb_y0 + vb_h)))
            gx += grid_step
        gy = math.floor(vb_y0 / grid_step) * grid_step
        while gy <= vb_y0 + vb_h:
            grid_g.add(dwg.line(start=(vb_x0, gy), end=(vb_x0 + vb_w, gy)))
            gy += grid_step

    if bool(style.get("show_coord_grid", False)) and grid_step > 0:
        _add_coord_labels(dwg, vb_x0, vb_y0, vb_w, vb_h, grid_step, max(dx, dy))

    for room in normalized["rooms"]:
        poly = room["_geom"]
        exterior = list(poly.exterior.coords)
        pts = [(x, y) for x, y in exterior]
        zt = room.get("zone_type", "other")
        fill_url = f"url(#{hatch_id})" if (zt == "storage" and hatch_storage) else room_fill
        fill_op = 0.85 if fill_url.startswith("url(") else 1.0
        dwg.add(
            dwg.polygon(
                points=pts,
                fill=fill_url,
                stroke="#111111",
                stroke_width=room_outline,
                fill_opacity=fill_op,
            )
        )
        c = poly.centroid
        if isinstance(c, Point) and not c.is_empty:
            dwg.add(
                dwg.text(
                    room["name"],
                    insert=(float(c.x), float(c.y)),
                    text_anchor="middle",
                    dominant_baseline="middle",
                    fill="#111111",
                    font_size=max(dx, dy) * 0.018,
                    font_family="sans-serif",
                )
            )

    for wi, w in enumerate(normalized["walls"]):
        ls = LineString([(w["x1"], w["y1"]), (w["x2"], w["y2"])])
        thick = max(w["thickness"], 0.5)
        wall_poly = ls.buffer(thick / 2.0, cap_style=2, join_style=2)
        ext = [(x, y) for x, y in wall_poly.exterior.coords]
        wid = w["id"] if str(w.get("id", "")).strip() else f"w{wi}"
        g = dwg.add(dwg.g(id=f"wall_{wid}"))
        g.add(
            dwg.polygon(
                points=ext,
                fill="#1a1a1a",
                stroke="#000000",
                stroke_width=wall_stroke * 0.35,
            )
        )

    eq_layer = dwg.add(dwg.g(id="equipment"))
    sorted_eq = sorted(normalized.get("equipment") or [], key=lambda e: e.get("z_index", 0))
    pat_for_hatch = f"url(#{hatch_id})"
    for eq in sorted_eq:
        x0, y0, lw, lh, rot = _equipment_transform(eq)
        cx, cy = x0 + lw / 2, y0 + lh / 2
        inner = dwg.g(
            transform=f"translate({cx:.4f},{cy:.4f}) rotate({-rot:.4f}) translate({-lw / 2:.4f},{-lh / 2:.4f})"
        )
        for op in _resolve_ops(eq, lw, lh):
            ph = pat_for_hatch if str(op.get("op")) == "hatch_rect" else None
            _apply_op(dwg, inner, op, eq_stroke, ph)
        rh = _external_raster_href(eq.get("representation") or {})
        if rh:
            inner.add(
                dwg.image(
                    href=rh,
                    insert=(0, 0),
                    size=(lw, lh),
                    preserveAspectRatio="xMidYMid meet",
                )
            )
        grp = dwg.g(id=f"eq_{eq['id']}")
        grp.add(inner)
        cgeom = eq["_footprint"].centroid
        if isinstance(cgeom, Point) and not cgeom.is_empty:
            grp.add(
                dwg.text(
                    eq["label"],
                    insert=(float(cgeom.x), float(cgeom.y)),
                    text_anchor="middle",
                    dominant_baseline="middle",
                    fill="#000000",
                    font_size=max(dx, dy) * 0.014,
                    font_family="sans-serif",
                )
            )
        eq_layer.add(grp)

    _embed_external_svg_layer(dwg, sorted_eq)
    _draw_callouts(dwg, normalized, max(dx, dy))
    _draw_scale_bar_title(dwg, normalized, vb_x0, vb_y0, vb_w, vb_h, margin, dx, dy, wall_stroke)
    return dwg.tostring()


def svg_to_pdf(svg_str: str, path: Path) -> None:
    if cairosvg is None:
        raise RuntimeError("cairo_missing: установите cairosvg (Cairo) для PDF")
    cairosvg.svg2pdf(bytestring=svg_str.encode("utf-8"), write_to=str(path))


def svg_to_png(svg_str: str, path: Path, dpi: int = 150) -> None:
    if cairosvg is None:
        raise RuntimeError("cairo_missing: установите cairosvg (Cairo) для PNG из SVG")
    scale = dpi / 77.0
    png_bytes = cairosvg.svg2png(bytestring=svg_str.encode("utf-8"), scale=scale)
    path.write_bytes(png_bytes)


def matplotlib_png_fallback(spec_no_geom: Dict[str, Any], path: Path, dpi: int = 150) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MplPoly
    from matplotlib.patches import Rectangle

    rooms: List[Dict[str, Any]] = []
    for r in spec_no_geom["rooms"]:
        rooms.append({"id": r["id"], "name": r["name"], "polygon": r["polygon"], "zone_type": r.get("zone_type", "other")})

    rooms_for_bounds: List[Dict[str, Any]] = []
    for r in rooms:
        coords = _normalize_polygon(r["polygon"])
        rooms_for_bounds.append({**r, "_geom": Polygon(coords)})
    eq_for_bounds: List[Dict[str, Any]] = []
    for eq in spec_no_geom.get("equipment") or []:
        try:
            eq_for_bounds.append({"_footprint": _equipment_footprint_geom(eq)})
        except (KeyError, ValueError):
            continue

    minx, miny, maxx, maxy = _bounds(
        {"rooms": rooms_for_bounds, "walls": spec_no_geom.get("walls") or [], "equipment": eq_for_bounds}
    )
    dx = maxx - minx or 1.0
    fig, ax = plt.subplots(figsize=(11.69, 8.27), dpi=dpi)
    ax.set_aspect("equal")
    ax.set_xlim(minx - dx * 0.1, maxx + dx * 0.1)
    ax.set_ylim(miny - dx * 0.1, maxy + dx * 0.1)
    ax.set_facecolor("white")
    ax.axis("off")

    profile = str(normalize_style_profile(spec_no_geom))
    palette = list(spec_no_geom.get("style", {}).get("room_palette") or DEFAULT_PALETTE)

    for i, room in enumerate(rooms):
        poly = room["polygon"] + [room["polygon"][0]]
        if profile == "technical_bw":
            fc = "#fafafa"
            if room.get("zone_type") == "storage":
                fc = "#e8e8e8"
            patch = MplPoly(poly, closed=True, facecolor=fc, edgecolor="#111", linewidth=1.0)
        else:
            patch = MplPoly(
                poly,
                closed=True,
                facecolor=palette[i % len(palette)],
                edgecolor="#222",
                linewidth=1.2,
            )
        ax.add_patch(patch)
        xs = [p[0] for p in room["polygon"]]
        ys = [p[1] for p in room["polygon"]]
        ax.text(sum(xs) / len(xs), sum(ys) / len(ys), room["name"], ha="center", va="center", fontsize=9)

    for eq in spec_no_geom.get("equipment") or []:
        try:
            fp = _equipment_footprint_geom(eq)
        except (KeyError, ValueError):
            continue
        x0, y0, x1, y1 = fp.bounds
        ax.add_patch(
            Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor="#111", linewidth=1.0)
        )
        ax.text((x0 + x1) / 2, (y0 + y1) / 2, eq.get("label", ""), ha="center", va="center", fontsize=7)

    ax.set_title(spec_no_geom["title"])
    fig.savefig(path, bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)


def normalize_style_profile(spec: Dict[str, Any]) -> str:
    st = spec.get("style") or {}
    p = str(st.get("render_profile", "schematic"))
    return p if p in ("schematic", "technical_bw") else "schematic"


def user_output_dir(output_dir: str) -> Optional[Path]:
    """Путь для сохранения артефактов: пусто → None (run_pipeline использует /tmp); ~ раскрывается."""
    s = (output_dir or "").strip()
    if not s:
        return None
    return Path(s).expanduser()


def run_pipeline(
    spec: Dict[str, Any],
    outputs: List[str],
    output_dir: Optional[Path],
    dpi: int = 150,
    page_size: str = "A4",
    orientation: str = "landscape",
) -> Dict[str, Any]:
    _ = page_size
    _ = orientation

    normalized, warnings = validate_and_normalize(spec)
    bbox = list(_bounds(normalized))
    svg = spec_to_svg(normalized)
    run_id = uuid.uuid4().hex[:8]
    out = output_dir or Path("/tmp")
    out.mkdir(parents=True, exist_ok=True)

    stem = f"floorplan_{run_id}"
    paths: Dict[str, str] = {}
    errors: List[str] = []

    if "svg" in outputs:
        p = out / f"{stem}.svg"
        p.write_text(svg, encoding="utf-8")
        paths["svg"] = str(p)

    if "pdf" in outputs:
        p = out / f"{stem}.pdf"
        try:
            svg_to_pdf(svg, p)
            paths["pdf"] = str(p)
        except Exception as e:  # noqa: BLE001
            errors.append(f"pdf: {e}")

    if "png" in outputs:
        p = out / f"{stem}.png"
        try:
            svg_to_png(svg, p, dpi=dpi)
            paths["png"] = str(p)
        except Exception as e:  # noqa: BLE001
            errors.append(f"png_svg: {e}")
            try:
                fal = spec_payload_for_fallback(normalized)
                matplotlib_png_fallback(fal, p, dpi=dpi)
                paths["png"] = str(p)
                warnings.append("png_used_matplotlib_fallback")
            except Exception as e2:  # noqa: BLE001
                errors.append(f"png_fallback: {e2}")

    cleaned = strip_geom(normalized)

    has_paths = bool(paths)
    if errors and not has_paths:
        status = "error"
    elif errors:
        status = "partial_failure"
    else:
        status = "success"

    return {
        "status": status,
        "paths": paths,
        "warnings": warnings,
        "errors": errors,
        "bounding_box": bbox,
        "normalized_spec": cleaned,
    }


def spec_payload_for_fallback(norm: Dict[str, Any]) -> Dict[str, Any]:
    rooms = [{"id": r["id"], "name": r["name"], "polygon": r["polygon"], "zone_type": r.get("zone_type", "other")} for r in norm["rooms"]]
    eqs = []
    for e in norm.get("equipment") or []:
        ee = {k: v for k, v in e.items() if k != "_footprint"}
        eqs.append(ee)
    return {
        "version": norm["version"],
        "units": norm["units"],
        "title": norm["title"],
        "rooms": rooms,
        "walls": norm["walls"],
        "equipment": eqs,
        "style": norm["style"],
    }


def strip_geom(normalized: Dict[str, Any]) -> Dict[str, Any]:
    rooms = []
    for r in normalized["rooms"]:
        rr = dict(r)
        rr.pop("_geom", None)
        rooms.append(rr)
    eqs = []
    for e in normalized.get("equipment") or []:
        ee = dict(e)
        ee.pop("_footprint", None)
        eqs.append(ee)
    out = dict(normalized)
    out["rooms"] = rooms
    out["equipment"] = eqs
    return out

def _floorplan_export_pdf_run(svg_path: str = "", output_path: str = "") -> dict:
    if not svg_path:
        return {"status": "error", "message": "svg_path_required", "pdf_path": None}
    p_in = Path(svg_path)
    if not p_in.exists():
        return {"status": "error", "message": f"file_not_found: {svg_path}", "pdf_path": None}
    svg_str = p_in.read_text(encoding="utf-8")
    if output_path:
        p_out = Path(output_path)
    else:
        p_out = p_in.with_suffix(".pdf")
    try:
        svg_to_pdf(svg_str, p_out)
        return {"status": "success", "pdf_path": str(p_out)}
    except Exception as e:
        return {"status": "error", "message": str(e), "pdf_path": None}
