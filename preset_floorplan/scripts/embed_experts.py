#!/usr/bin/env python3
"""Собирает тела экспертов Extella: встраивает preset_floorplan/python/floorplan_core.py."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE_PATH = ROOT / "python" / "floorplan_core.py"
OUT = ROOT / "experts"


HEADER = """$extens("include.py")
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
"""

OPENAI_INCLUDE = 'include("import openai", ["extella-pip install openai"])\n'

MERGE_HEADER = """$extens("include.py")
include("import json", [])
include("from pathlib import Path", [])
include("from typing import Any, Dict, List", [])
"""

MERGE_PATH = ROOT / "python" / "floorplan_layout_merge.py"
TOOLS_PATH = ROOT / "python" / "floorplan_openai_tools.py"


def load_py(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    lines_out: list[str] = []
    for line in text.splitlines():
        if line.strip() == "from __future__ import annotations":
            continue
        lines_out.append(line)
    return "\n".join(lines_out).strip() + "\n"


def load_core_source() -> str:
    return load_py(CORE_PATH)


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

    merge_src = load_py(MERGE_PATH)
    tools_src = load_py(TOOLS_PATH)
    openai_header = HEADER + OPENAI_INCLUDE

    write(
        OUT / "floorplan_layout_draft_merge.py",
        MERGE_HEADER + "\n" + merge_src
        + """
def floorplan_layout_draft_merge(
    layout_draft_json: str = "",
    title: str = "",
    render_profile: str = "technical_bw",
    show_grid: bool = True,
) -> dict:
    try:
        draft = json.loads(layout_draft_json) if layout_draft_json else {}
    except json.JSONDecodeError as e:
        return {"status": "error", "message": f"invalid_json: {e}", "spec_json": ""}
    try:
        spec = merge_layout_draft_to_spec(
            draft,
            render_profile=str(render_profile),
            show_grid=bool(show_grid),
        )
        if title and str(title).strip():
            spec["title"] = str(title).strip()
        return {
            "status": "success",
            "spec_json": json.dumps(spec, ensure_ascii=False),
        }
    except ValueError as e:
        return {"status": "error", "message": str(e), "spec_json": ""}
""",
    )

    write(
        OUT / "floorplan_openai_layout.py",
        openai_header + "\n" + merge_src + "\n" + tools_src
        + """
def floorplan_openai_layout(
    user_brief: str = "",
    units: str = "cm",
    openai_api_key: str = "",
    model: str = "gpt-4o-mini",
    render_profile: str = "technical_bw",
    show_grid: bool = True,
) -> dict:
    if not (user_brief or "").strip():
        return {"status": "error", "message": "user_brief_required", "layout_draft": None, "spec_json": ""}
    try:
        key = resolve_openai_key(openai_api_key)
        system = (
            "Ты инженер по планировке. Отвечай только валидным JSON без markdown. "
            + LAYOUT_JSON_INSTRUCTIONS
        )
        user_msg = f"Единицы: {units}. Задача:\\n{user_brief.strip()}"
        draft = openai_chat_json(api_key=key, model=str(model), system=system, user=user_msg)
        if draft.get("version") != 1:
            draft["version"] = 1
        if "units" not in draft:
            draft["units"] = units
        spec = merge_layout_draft_to_spec(
            draft,
            render_profile=str(render_profile),
            show_grid=bool(show_grid),
        )
        return {
            "status": "success",
            "layout_draft": draft,
            "spec_json": json.dumps(spec, ensure_ascii=False),
            "warnings": [],
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "layout_draft": None, "spec_json": ""}
""",
    )

    write(
        OUT / "floorplan_openai_equipment_images.py",
        openai_header + "\n" + tools_src
        + """
def floorplan_openai_equipment_images(
    spec_json: str = "",
    output_dir: str = "",
    openai_api_key: str = "",
    image_model: str = "dall-e-3",
    skip_existing: bool = True,
) -> dict:
    try:
        spec = json.loads(spec_json) if spec_json else {}
    except json.JSONDecodeError as e:
        return {"status": "error", "message": f"invalid_json: {e}", "spec_json": "", "paths": []}
    if spec.get("version") != 2:
        return {"status": "error", "message": "requires_version_2", "spec_json": "", "paths": []}
    odir = Path(output_dir) if output_dir else Path("/tmp")
    odir.mkdir(parents=True, exist_ok=True)
    try:
        key = resolve_openai_key(openai_api_key)
    except ValueError as e:
        return {"status": "error", "message": str(e), "spec_json": "", "paths": []}
    paths: List[str] = []
    warnings: List[str] = []
    for eq in spec.get("equipment") or []:
        eid = str(eq.get("id", "eq"))
        rep = eq.get("representation") or {}
        hint = str(rep.get("openai_image_hint") or eq.get("label") or eid)
        png = odir / f"equipment_{eid}.png"
        if skip_existing and png.is_file():
            warnings.append(f"skip_existing:{eid}")
        else:
            prompt = (
                "Technical CAD-style line drawing, orthographic top-down view, thin black lines "
                "on pure white background, no text, no dimensions, single isolated industrial unit: "
                + hint[:2000]
            )
            try:
                openai_save_image(api_key=key, prompt=prompt, out_path=png, model=str(image_model))
            except Exception as e:
                return {"status": "error", "message": f"{eid}: {e}", "spec_json": spec_json, "paths": paths}
        rep = dict(rep)
        rep["external_raster"] = {"path": str(png.resolve())}
        eq["representation"] = rep
        paths.append(str(png.resolve()))
    return {
        "status": "success",
        "spec_json": json.dumps(spec, ensure_ascii=False),
        "paths": paths,
        "warnings": warnings,
    }
""",
    )

    write(
        OUT / "floorplan_openai_overview_image.py",
        openai_header + "\n" + tools_src
        + """
def floorplan_openai_overview_image(
    summary_text: str = "",
    output_dir: str = "",
    openai_api_key: str = "",
    image_model: str = "dall-e-3",
) -> dict:
    if not (summary_text or "").strip():
        return {"status": "error", "message": "summary_text_required", "png_path": None}
    odir = Path(output_dir) if output_dir else Path("/tmp")
    odir.mkdir(parents=True, exist_ok=True)
    out = odir / f"floorplan_overview_{uuid.uuid4().hex[:8]}.png"
    try:
        key = resolve_openai_key(openai_api_key)
        prompt = (
            "Industrial facility floor plan from above, technical schematic, black lines on white, "
            "no readable text, orthographic layout illustration:\\n"
            + summary_text.strip()[:6000]
        )
        openai_save_image(api_key=key, prompt=prompt, out_path=out, model=str(image_model))
        return {"status": "success", "png_path": str(out.resolve())}
    except Exception as e:
        return {"status": "error", "message": str(e), "png_path": None}
""",
    )

    full_wrapper = '''
def floorplan_full_openai_pipeline(
    user_brief: str = "",
    units: str = "cm",
    openai_api_key: str = "",
    chat_model: str = "gpt-4o-mini",
    image_model: str = "dall-e-3",
    outputs: str = "pdf,png,svg",
    output_dir: str = "",
    dpi: int = 150,
    page_size: str = "A4",
    orientation: str = "landscape",
    render_profile: str = "technical_bw",
    show_grid: bool = True,
    skip_equipment_images: bool = False,
    skip_overview: bool = False,
    skip_existing_images: bool = True,
) -> dict:
    warnings: List[str] = []
    errors: List[str] = []
    layout_draft_json: Optional[str] = None
    eq_paths: List[str] = []
    overview_path: Optional[str] = None
    try:
        key = resolve_openai_key(openai_api_key)
        odir = Path(output_dir) if output_dir else Path("/tmp")
        odir.mkdir(parents=True, exist_ok=True)
        if not (user_brief or "").strip():
            raise ValueError("user_brief_required")
        system = (
            "Ты инженер по планировке. Отвечай только валидным JSON без markdown. "
            + LAYOUT_JSON_INSTRUCTIONS
        )
        user_msg = f"Единицы: {units}. Задача:\\n{user_brief.strip()}"
        draft = openai_chat_json(api_key=key, model=str(chat_model), system=system, user=user_msg)
        if draft.get("version") != 1:
            draft["version"] = 1
        if "units" not in draft:
            draft["units"] = units
        layout_draft_json = json.dumps(draft, ensure_ascii=False)
        spec = merge_layout_draft_to_spec(
            draft,
            render_profile=str(render_profile),
            show_grid=bool(show_grid),
        )
        if not skip_equipment_images:
            for eq in spec.get("equipment") or []:
                eid = str(eq.get("id", "eq"))
                rep = eq.get("representation") or {}
                hint = str(rep.get("openai_image_hint") or eq.get("label") or eid)
                png = odir / f"equipment_{eid}.png"
                if skip_existing_images and png.is_file():
                    warnings.append(f"skip_existing:{eid}")
                else:
                    prompt = (
                        "Technical CAD-style line drawing, orthographic top-down view, thin black lines "
                        "on pure white background, no text, no dimensions, single isolated industrial unit: "
                        + hint[:2000]
                    )
                    try:
                        openai_save_image(
                            api_key=key, prompt=prompt, out_path=png, model=str(image_model)
                        )
                    except Exception as e:
                        errors.append(f"equipment_image {eid}: {e}")
                        continue
                rep = dict(rep)
                rep["external_raster"] = {"path": str(png.resolve())}
                eq["representation"] = rep
                eq_paths.append(str(png.resolve()))
        if not skip_overview:
            lines = [str(spec.get("title", "")), f"Units: {spec.get('units')}"]
            for eq in spec.get("equipment") or []:
                bb = eq.get("bbox") or {}
                lines.append(
                    f"- {eq.get('id')}: {eq.get('label')} @({bb.get('x')},{bb.get('y')}) {bb.get('width')}x{bb.get('height')}"
                )
            op = odir / f"floorplan_overview_{uuid.uuid4().hex[:8]}.png"
            oprompt = (
                "Industrial floor plan top-down schematic, black technical lines on white, "
                "no readable text, overview:\\n" + "\\n".join(lines)[:6000]
            )
            try:
                openai_save_image(api_key=key, prompt=oprompt, out_path=op, model=str(image_model))
                overview_path = str(op.resolve())
            except Exception as e:
                errors.append(f"overview: {e}")
        outs = [x.strip().lower() for x in str(outputs).split(",") if x.strip()]
        if not outs:
            outs = ["svg"]
        result = run_pipeline(
            spec,
            outs,
            odir,
            dpi=int(dpi),
            page_size=str(page_size),
            orientation=str(orientation),
        )
        if isinstance(result, dict):
            result["layout_draft_json"] = layout_draft_json
            result["equipment_image_paths"] = eq_paths
            result["overview_png_path"] = overview_path
            for w in warnings:
                result.setdefault("warnings", []).append(w)
            for e in errors:
                result.setdefault("errors", []).append(e)
        return result
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "paths": {},
            "warnings": warnings,
            "errors": errors + [str(e)],
            "bounding_box": None,
            "normalized_spec": None,
            "layout_draft_json": layout_draft_json,
            "equipment_image_paths": eq_paths,
            "overview_png_path": overview_path,
        }
'''

    write(
        OUT / "floorplan_full_openai_pipeline.py",
        openai_header + "\n" + core + "\n" + merge_src + "\n" + tools_src + "\n" + full_wrapper,
    )

    print("Written experts to", OUT)


if __name__ == "__main__":
    main()
