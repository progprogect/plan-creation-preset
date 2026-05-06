$extens("include.py")
include("import json", [])
include("from pathlib import Path", [])
include("from typing import Any, Dict, List, Optional, Tuple", [])
include("import math", [])
include("import uuid", [])
include("import shapely.geometry", ["extella-pip install shapely"])
include("from shapely.geometry import LineString, Point, Polygon", [])
include("from shapely.ops import unary_union", [])
include("import svgwrite", ["extella-pip install svgwrite"])
include("import cairosvg", ["extella-pip install cairosvg"])
include("import matplotlib", ["extella-pip install matplotlib"])


"""
Каноническая логика пресета планов помещений: валидация, SVG, экспорт PDF∕PNG.
Можно использовать локально; тела экспертов Extella дублируют эти функции или
подключают модуль, если окружение позволяет.
"""


import math
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

try:
    import cairosvg
except Exception:  # noqa: BLE001 — optional dependency
    cairosvg = None  # type: ignore

import svgwrite

DEFAULT_PALETTE = [
    "#e8f4f8",
    "#fff4e6",
    "#e8f8e8",
    "#f0e8ff",
    "#fce8ec",
    "#f5f5dc",
]


def _units_label(units: str) -> str:
    return {"mm": "mm", "cm": "cm", "m": "m"}.get(units, units)


def _normalize_polygon(ring: List[List[float]]) -> List[Tuple[float, float]]:
    if not ring:
        return []
    pts: List[Tuple[float, float]] = [(float(p[0]), float(p[1])) for p in ring if len(p) >= 2]
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def validate_and_normalize(spec: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    if spec.get("version") != 1:
        raise ValueError("unsupported_version: ожидается version == 1")

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

    style = dict(spec.get("style") or {})
    normalized: Dict[str, Any] = {
        "version": 1,
        "units": units,
        "title": str(spec.get("title") or "Floor plan"),
        "metadata": dict(spec.get("metadata") or {}),
        "rooms": rooms_out,
        "walls": walls_out,
        "openings": list(spec.get("openings") or []),
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
    if not geoms:
        return 0.0, 0.0, 100.0, 100.0
    u = unary_union(geoms)
    minx, miny, maxx, maxy = u.bounds
    return float(minx), float(miny), float(maxx), float(maxy)


def spec_to_svg(normalized: Dict[str, Any], margin_ratio: float = 0.08) -> str:
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

    # background
    dwg.add(
        dwg.rect(
            insert=(vb_x0, vb_y0),
            size=(vb_w, vb_h),
            fill="white",
            stroke="none",
        )
    )

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

    rooms = []
    for r in spec_no_geom["rooms"]:
        rooms.append({"id": r["id"], "name": r["name"], "polygon": r["polygon"]})

    minx, miny, maxx, maxy = _bounds({"rooms": rooms, "walls": spec_no_geom.get("walls") or []})
    dx = maxx - minx or 1.0
    fig, ax = plt.subplots(figsize=(11.69, 8.27), dpi=dpi)
    ax.set_aspect("equal")
    ax.set_xlim(minx - dx * 0.1, maxx + dx * 0.1)
    ax.set_ylim(miny - dx * 0.1, maxy + dx * 0.1)
    ax.set_facecolor("white")
    ax.axis("off")

    palette = list(spec_no_geom.get("style", {}).get("room_palette") or DEFAULT_PALETTE)
    for i, room in enumerate(rooms):
        poly = room["polygon"] + [room["polygon"][0]]
        patch = MplPoly(poly, closed=True, facecolor=palette[i % len(palette)], edgecolor="#222", linewidth=1.2)
        ax.add_patch(patch)
        xs = [p[0] for p in room["polygon"]]
        ys = [p[1] for p in room["polygon"]]
        ax.text(sum(xs) / len(xs), sum(ys) / len(ys), room["name"], ha="center", va="center", fontsize=9)

    ax.set_title(spec_no_geom["title"])
    fig.savefig(path, bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)


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
                matplotlib_png_fallback(
                    {
                        "version": normalized["version"],
                        "units": normalized["units"],
                        "title": normalized["title"],
                        "rooms": [
                            {"id": r["id"], "name": r["name"], "polygon": r["polygon"]} for r in normalized["rooms"]
                        ],
                        "walls": normalized["walls"],
                        "style": normalized["style"],
                    },
                    p,
                    dpi=dpi,
                )
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

    result: Dict[str, Any] = {
        "status": status,
        "paths": paths,
        "warnings": warnings,
        "errors": errors,
        "bounding_box": bbox,
        "normalized_spec": cleaned,
    }
    return result


def strip_geom(normalized: Dict[str, Any]) -> Dict[str, Any]:
    rooms = []
    for r in normalized["rooms"]:
        rr = dict(r)
        rr.pop("_geom", None)
        rooms.append(rr)
    out = dict(normalized)
    out["rooms"] = rooms
    return out

def floorplan_export_png(svg_path: str = "", output_path: str = "", dpi: int = 150) -> dict:
    if not svg_path:
        return {"status": "error", "message": "svg_path_required", "png_path": None}
    p_in = Path(svg_path)
    if not p_in.exists():
        return {"status": "error", "message": f"file_not_found: {svg_path}", "png_path": None}
    svg_str = p_in.read_text(encoding="utf-8")
    if output_path:
        p_out = Path(output_path)
    else:
        p_out = p_in.with_suffix(".png")
    try:
        svg_to_png(svg_str, p_out, dpi=int(dpi))
        return {"status": "success", "png_path": str(p_out)}
    except Exception as e:
        return {"status": "error", "message": str(e), "png_path": None}
