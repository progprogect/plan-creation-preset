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
include("import openai", ["extella-pip install openai"])

"""
Черновик раскладки (layout_draft) → канонический floorplan_spec v2.
Без сетевых вызовов; используется экспертом merge и OpenAI layout.
"""


from typing import Any, Dict, List


def _draft_rooms_poly_ok(rooms: List[Dict[str, Any]]) -> None:
    for r in rooms:
        poly = r.get("polygon")
        if not isinstance(poly, list) or len(poly) < 3:
            raise ValueError(f"layout_draft: комната '{r.get('id')}' — polygon >= 3 точек")


def merge_layout_draft_to_spec(
    draft: Dict[str, Any],
    *,
    render_profile: str = "technical_bw",
    show_grid: bool = True,
) -> Dict[str, Any]:
    """
    Строит floorplan_spec v2: комнаты и оборудование с placeholder representation.
    Текст для генерации PNG: representation.openai_image_hint.
    """
    if draft.get("version") != 1:
        raise ValueError("layout_draft.version должен быть 1")
    units = draft.get("units")
    if units not in ("mm", "cm", "m"):
        raise ValueError("layout_draft.units: mm | cm | m")
    rooms_in = draft.get("rooms") or []
    if not rooms_in:
        raise ValueError("layout_draft: нужна минимум одна комната")
    _draft_rooms_poly_ok(rooms_in)

    title = str(draft.get("title") or "Floor plan")
    rooms_out: List[Dict[str, Any]] = []
    for idx, r in enumerate(rooms_in):
        rid = str(r.get("id", f"room_{idx}"))
        zt = r.get("zone_type", "other")
        if zt not in ("production", "storage", "other"):
            raise ValueError(f"room '{rid}': zone_type production|storage|other")
        rooms_out.append(
            {
                "id": rid,
                "name": str(r.get("name", rid)),
                "zone_type": zt,
                "polygon": r["polygon"],
            }
        )

    equipment_out: List[Dict[str, Any]] = []
    for ei, e in enumerate(draft.get("equipment") or []):
        if not isinstance(e, dict):
            raise ValueError(f"equipment #{ei} не объект")
        eid = str(e.get("id", f"eq_{ei}"))
        label = str(e.get("label", eid))
        bb = e.get("bbox")
        if not isinstance(bb, dict):
            raise ValueError(f"equipment '{eid}': нужен bbox")
        hint = str(e.get("text_description") or label)
        equipment_out.append(
            {
                "id": eid,
                "label": label,
                "z_index": float(e.get("z_index", 0)),
                "bbox": {
                    "x": float(bb["x"]),
                    "y": float(bb["y"]),
                    "width": float(bb["width"]),
                    "height": float(bb["height"]),
                    "rotation": float(bb.get("rotation", 0) or 0),
                },
                "representation": {
                    "library_key": "generic",
                    "openai_image_hint": hint,
                },
            }
        )

    spec: Dict[str, Any] = {
        "version": 2,
        "units": units,
        "title": title,
        "style": {
            "render_profile": render_profile if render_profile in ("schematic", "technical_bw") else "technical_bw",
            "show_grid": show_grid,
        },
        "rooms": rooms_out,
        "equipment": equipment_out,
    }
    if draft.get("annotations"):
        spec["annotations"] = dict(draft["annotations"])
    if draft.get("layout_notes"):
        spec.setdefault("metadata", {})["layout_notes"] = str(draft["layout_notes"])
    return spec


LAYOUT_JSON_INSTRUCTIONS = """Верни один JSON-объект (без markdown) со структурой layout_draft:
{
  "version": 1,
  "units": "cm"|"mm"|"m",
  "title": "краткий заголовок плана",
  "rooms": [ { "id", "name", "zone_type": "production"|"storage"|"other", "polygon": [[x,y],...] } ],
  "equipment": [ {
    "id": "строка_без_пробелов",
    "label": "краткая подпись",
    "bbox": { "x", "y", "width", "height", "rotation": 0 },
    "text_description": "для картинки: вид сверху, ортогональная схема одного узла, узел: ...",
    "z_index": 0
  } ],
  "annotations": { "callouts": [ { "id", "text", "target_id", "offset": { "dx", "dy" } } ] }  // опционально
}
Координаты в одних units; полигоны комнат простые без самопересечений; оборудование внутри контура зала."""

"""Вызовы OpenAI: Chat (JSON) и сохранение изображения (Images API). Без зависимости от floorplan_core."""


import base64
import json
import os
from pathlib import Path
from typing import Any, Dict


def resolve_openai_key(explicit: str = "") -> str:
    k = (explicit or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    if not k:
        raise ValueError("openai_api_key: задайте параметр эксперта или переменную OPENAI_API_KEY")
    return k


def openai_chat_json(
    *,
    api_key: str,
    model: str,
    system: str,
    user: str,
) -> Dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    r = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    raw = r.choices[0].message.content or "{}"
    return json.loads(raw)


def openai_save_image(
    *,
    api_key: str,
    prompt: str,
    out_path: Path,
    model: str = "dall-e-3",
    size: str = "1024x1024",
) -> None:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    resp = client.images.generate(
        model=model,
        prompt=prompt[:4000],
        size=size,
        quality="standard",
        n=1,
        response_format="b64_json",
    )
    b64 = resp.data[0].b64_json
    if not b64:
        raise RuntimeError("images.generate: пустой b64_json")
    out_path.write_bytes(base64.standard_b64decode(b64))

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
        user_msg = f"Единицы: {units}. Задача:\n{user_brief.strip()}"
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
