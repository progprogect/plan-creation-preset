"""Локальные smoke-тесты пресета (pytest)."""

import json
from pathlib import Path

import pytest

from floorplan_core import run_pipeline, validate_and_normalize

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
