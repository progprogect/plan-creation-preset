#!/usr/bin/env python3
"""Собирает тела экспертов Extella: встраивает preset_floorplan/python/floorplan_core.py."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE_PATH = ROOT / "python" / "floorplan_core.py"
OUT = ROOT / "experts"


HEADER = """$extens("include.py")
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


def load_core_source() -> str:
    text = CORE_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    out: list[str] = []
    for line in lines:
        if line.strip() == "from __future__ import annotations":
            continue
        out.append(line)
    return "\n".join(out).strip() + "\n"


def write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def main() -> None:
    core = load_core_source()
    base = HEADER + "\n\n" + core

    write(
        OUT / "floorplan_build_pipeline.py",
        base
        + """
def floorplan_build_pipeline(
    spec_json: str = "",
    outputs: str = "pdf,png,svg",
    output_dir: str = "",
    dpi: int = 150,
    page_size: str = "A4",
    orientation: str = "landscape",
) -> dict:
    try:
        spec = json.loads(spec_json) if spec_json else {}
    except json.JSONDecodeError as e:
        return {
            "status": "error",
            "message": f"invalid_json: {e}",
            "paths": {},
            "warnings": [],
            "errors": [str(e)],
            "bounding_box": None,
            "normalized_spec": None,
        }

    outs = [x.strip().lower() for x in outputs.split(",") if x.strip()]
    if not outs:
        outs = ["svg"]

    odir = Path(output_dir) if output_dir else None
    try:
        result = run_pipeline(
            spec,
            outs,
            odir,
            dpi=int(dpi),
            page_size=str(page_size),
            orientation=str(orientation),
        )
    except ValueError as e:
        return {
            "status": "error",
            "message": str(e),
            "paths": {},
            "warnings": [],
            "errors": [str(e)],
            "bounding_box": None,
            "normalized_spec": None,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "paths": {},
            "warnings": [],
            "errors": [str(e)],
            "bounding_box": None,
            "normalized_spec": None,
        }
    return result
""",
    )

    write(
        OUT / "floorplan_spec_validate.py",
        base
        + """
def floorplan_spec_validate(spec_json: str = "") -> dict:
    try:
        spec = json.loads(spec_json) if spec_json else {}
    except json.JSONDecodeError as e:
        return {
            "status": "error",
            "message": f"invalid_json: {e}",
            "normalized_spec": None,
            "warnings": [],
            "bounding_box": None,
        }
    try:
        normalized, warnings = validate_and_normalize(spec)
        cleaned = strip_geom(normalized)
        bbox = list(_bounds(normalized))
        return {
            "status": "success",
            "normalized_spec": cleaned,
            "warnings": warnings,
            "bounding_box": bbox,
        }
    except ValueError as e:
        return {
            "status": "error",
            "message": str(e),
            "normalized_spec": None,
            "warnings": [],
            "bounding_box": None,
        }
""",
    )

    write(
        OUT / "floorplan_render_svg.py",
        base
        + """
def floorplan_render_svg(spec_json: str = "", output_dir: str = "") -> dict:
    try:
        spec = json.loads(spec_json) if spec_json else {}
    except json.JSONDecodeError as e:
        return {"status": "error", "message": f"invalid_json: {e}", "svg_path": None, "warnings": []}
    try:
        normalized, warnings = validate_and_normalize(spec)
        svg = spec_to_svg(normalized)
        out = Path(output_dir) if output_dir else Path("/tmp")
        out.mkdir(parents=True, exist_ok=True)
        stem = f"floorplan_svg_{uuid.uuid4().hex[:8]}"
        path = out / f"{stem}.svg"
        path.write_text(svg, encoding="utf-8")
        cleaned = strip_geom(normalized)
        return {
            "status": "success",
            "svg_path": str(path),
            "warnings": warnings,
            "bounding_box": list(_bounds(normalized)),
            "normalized_spec": cleaned,
        }
    except ValueError as e:
        return {"status": "error", "message": str(e), "svg_path": None, "warnings": []}
""",
    )

    write(
        OUT / "floorplan_export_pdf.py",
        base
        + """
def floorplan_export_pdf(svg_path: str = "", output_path: str = "") -> dict:
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
""",
    )

    write(
        OUT / "floorplan_export_png.py",
        base
        + """
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
""",
    )

    print("Written experts to", OUT)


if __name__ == "__main__":
    main()
