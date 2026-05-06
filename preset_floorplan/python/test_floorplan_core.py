"""Локальные smoke-тесты пресета (pytest)."""

import base64
import json
from pathlib import Path

import pytest

from floorplan_core import run_pipeline, spec_to_svg, validate_and_normalize
from floorplan_layout_merge import merge_layout_draft_to_spec

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_validate_studio():
    spec = json.loads((EXAMPLES / "studio.json").read_text(encoding="utf-8"))
    norm, w = validate_and_normalize(spec)
    assert norm["version"] == 1
    assert len(norm["rooms"]) == 1
    assert not w


def test_pipeline_svg_only(tmp_path):
    spec = json.loads((EXAMPLES / "l_shape.json").read_text(encoding="utf-8"))
    res = run_pipeline(spec, ["svg"], tmp_path, dpi=120)
    assert res["status"] == "success"
    assert "svg" in res["paths"]
    assert Path(res["paths"]["svg"]).exists()


def test_pipeline_invalid_polygon():
    spec = {
        "version": 1,
        "units": "cm",
        "rooms": [{"id": "x", "name": "Bad", "polygon": [[0, 0], [1, 1]]}],
    }
    with pytest.raises(ValueError, match="invalid_polygon|меньше"):
        validate_and_normalize(spec)


def test_technical_v2_pipeline(tmp_path):
    spec = json.loads((EXAMPLES / "production_line_technical_v2.json").read_text(encoding="utf-8"))
    res = run_pipeline(spec, ["svg"], tmp_path, dpi=120)
    assert res["status"] == "success"
    svg_text = Path(res["paths"]["svg"]).read_text(encoding="utf-8")
    assert "diagHatch" in svg_text or "eq_" in svg_text
    assert res["normalized_spec"]["version"] == 2
    assert len(res["normalized_spec"]["equipment"]) == 3


def test_v2_schematic_draws_equipment():
    """В v2 + schematic оборудование должно быть видно (иначе только bbox без графики)."""
    spec = {
        "version": 2,
        "units": "cm",
        "title": "s",
        "style": {"render_profile": "schematic", "show_grid": False},
        "rooms": [
            {
                "id": "r1",
                "name": "R",
                "zone_type": "other",
                "polygon": [[0, 0], [300, 0], [300, 200], [0, 200]],
            }
        ],
        "equipment": [
            {
                "id": "e1",
                "label": "M",
                "bbox": {"x": 50, "y": 50, "width": 40, "height": 30},
                "representation": {"library_key": "generic"},
            }
        ],
    }
    n, _ = validate_and_normalize(spec)
    svg = spec_to_svg(n)
    assert "equipment_schematic" in svg
    assert "stroke-dasharray" in svg or "stroke_dasharray" in svg


def test_v2_parametric_custom():
    spec = {
        "version": 2,
        "units": "cm",
        "title": "p",
        "style": {"render_profile": "technical_bw", "show_grid": False},
        "rooms": [
            {
                "id": "r1",
                "name": "R",
                "zone_type": "other",
                "polygon": [[0, 0], [400, 0], [400, 300], [0, 300]],
            }
        ],
        "equipment": [
            {
                "id": "custom",
                "label": "custom",
                "bbox": {"x": 50, "y": 50, "width": 100, "height": 80, "rotation": 0},
                "representation": {
                    "parametric_symbol": [
                        {"op": "rect", "x": 0, "y": 0, "w": 100, "h": 80, "fill": False},
                        {"op": "circle", "cx": 50, "cy": 40, "r": 15},
                    ]
                },
            }
        ],
    }
    n, _ = validate_and_normalize(spec)
    svg = spec_to_svg(n)
    assert "r=\"15\"" in svg or "circle" in svg


def test_merge_layout_draft():
    draft = {
        "version": 1,
        "units": "cm",
        "title": "Hall",
        "rooms": [
            {"id": "r1", "name": "Production", "zone_type": "production", "polygon": [[0, 0], [200, 0], [200, 100], [0, 100]]},
        ],
        "equipment": [
            {
                "id": "m1",
                "label": "Machine",
                "bbox": {"x": 40, "y": 30, "width": 50, "height": 40, "rotation": 0},
                "text_description": "conveyor top view",
            }
        ],
    }
    spec = merge_layout_draft_to_spec(draft, render_profile="technical_bw", show_grid=False)
    assert spec["version"] == 2
    assert spec["equipment"][0]["representation"]["openai_image_hint"] == "conveyor top view"
    n, w = validate_and_normalize(spec)
    assert len(n["rooms"]) == 1
    assert not w


def test_external_raster_in_technical_svg(tmp_path):
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    img_path = tmp_path / "eq.png"
    img_path.write_bytes(png_bytes)
    spec = {
        "version": 2,
        "units": "cm",
        "title": "r",
        "style": {"render_profile": "technical_bw", "show_grid": False},
        "rooms": [
            {
                "id": "r1",
                "name": "R",
                "zone_type": "other",
                "polygon": [[0, 0], [300, 0], [300, 200], [0, 200]],
            }
        ],
        "equipment": [
            {
                "id": "e1",
                "label": "X",
                "bbox": {"x": 50, "y": 50, "width": 80, "height": 60, "rotation": 0},
                "representation": {"external_raster": {"path": str(img_path)}},
            }
        ],
    }
    n, _ = validate_and_normalize(spec)
    svg = spec_to_svg(n)
    assert "image" in svg
    assert "file://" in svg or str(img_path.resolve()) in svg
