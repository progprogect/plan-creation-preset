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

def floorplan_openai_layout(
    user_brief: str = "",
    units: str = "cm",
    openai_api_key: str = "",
    model: str = "gpt-4o-mini",
    render_profile: str = "technical_bw",
    show_grid: bool = True,
) -> dict:
    """fython: первая top-level def (до merge_layout_draft_to_spec)."""
    return _floorplan_openai_layout_run(
        user_brief=user_brief,
        units=units,
        openai_api_key=openai_api_key,
        model=model,
        render_profile=render_profile,
        show_grid=show_grid,
    )

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
from typing import Any, Dict, List


def output_dir_path(output_dir: str) -> Path:
    """Каталог для PNG и пр.: пусто → /tmp; пути с ~ раскрываются (Extella Desktop)."""
    s = (output_dir or "").strip()
    if not s:
        return Path("/tmp")
    return Path(s).expanduser()


def build_full_floorplan_openai_prompt(spec: Dict[str, Any]) -> str:
    """
    Один промпт для GPT Image: целый план сверху по данным spec (без _geom).
    Геометрия в SVG остаётся канонической; это растр для визуально ровного итога.
    """
    units = spec.get("units", "cm")
    title = spec.get("title", "Floor plan")
    st = spec.get("style") or {}
    grid = st.get("show_grid", True)
    grid_step = st.get("grid_step")
    profile = st.get("render_profile", "technical_bw")
    lines: List[str] = [
        "Single orthographic TOP-DOWN industrial floor plan. Flat 2D only, no perspective, no 3D render.",
        "Visual style: crisp thin BLACK linework on pure WHITE background, technical CAD / line drawing,",
        "no photorealistic textures, no shadows, no gradients. Clean and readable.",
        f"Caption allowed once (small): {json.dumps(title, ensure_ascii=False)}. All numeric data below in units: {units}.",
        f"Render profile intent: {profile}. Light square grid: {'on' if grid else 'off'}.",
    ]
    if grid_step is not None:
        lines.append(f"Grid step: {grid_step} {units}.")
    lines.append("ROOMS — draw each as closed polygon (vertex order as given):")
    for r in spec.get("rooms") or []:
        poly = r.get("polygon")
        if isinstance(poly, list) and len(poly) >= 2:
            lines.append(
                f"  room_id={r.get('id')} name={json.dumps(r.get('name',''), ensure_ascii=False)} "
                f"zone_type={r.get('zone_type','other')} polygon={json.dumps(poly, ensure_ascii=False)}"
            )
    lines.append("EQUIPMENT — top-down symbols inside room, rectangles unless rotation specified:")
    for e in spec.get("equipment") or []:
        bb = e.get("bbox") or {}
        hint = ""
        rep = e.get("representation") or {}
        if isinstance(rep, dict):
            hint = str(rep.get("openai_image_hint") or "")[:400]
        lines.append(
            f"  eq_id={e.get('id')} label={json.dumps(e.get('label',''), ensure_ascii=False)} "
            f"x={bb.get('x')} y={bb.get('y')} w={bb.get('width')} h={bb.get('height')} "
            f"rotation_deg={bb.get('rotation', 0)} symbol_hint={json.dumps(hint, ensure_ascii=False)}"
        )
    callouts = (spec.get("annotations") or {}).get("callouts") or []
    if callouts:
        lines.append("NUMBERED CALLOUTS — small circles/leaders, minimal text:")
        for c in callouts:
            lines.append(
                f"  id={c.get('id')} text={json.dumps(str(c.get('text','')), ensure_ascii=False)} "
                f"target_equipment={c.get('target_id')}"
            )
    lines.append(
        "Keep equipment symbols schematic (conveyors as parallel lines, robot as circle + arm hint, pallets as small rectangles). "
        "Respect relative placement and proportions from coordinates; center the whole layout in the frame."
    )
    return "\n".join(lines)[:31000]


def coerce_image_size(model: str, size: str) -> str:
    """
    Размеры зависят от модели: DALL·E 3 не принимает 1536×1024 (только GPT Image).
    См. https://developers.openai.com/api/docs/guides/images
    """
    m = (model or "").strip().lower()
    s = (size or "1024x1024").strip()
    if m.startswith("gpt-image-"):
        if s in ("1024x1024", "1536x1024", "1024x1536", "auto"):
            return s
        return "1024x1024"
    if "dall-e-3" in m:
        if s in ("1024x1024", "1792x1024", "1024x1792"):
            return s
        if s in ("1536x1024", "1024x1536"):
            return "1792x1024" if "1536" in s else "1024x1792"
        return "1024x1024"
    if "dall-e-2" in m:
        if s in ("256x256", "512x512", "1024x1024"):
            return s
        return "1024x1024"
    return s or "1024x1024"


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
    model: str = "gpt-image-1.5",
    size: str = "1024x1024",
) -> None:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    m = (model or "gpt-image-1.5").strip().lower()
    size = coerce_image_size(model, size)
    is_gpt_image = m.startswith("gpt-image-")
    kwargs: Dict[str, Any] = {"model": model, "prompt": prompt, "n": 1}
    if is_gpt_image:
        kwargs["prompt"] = prompt[:32000]
        if size in ("1024x1024", "1536x1024", "1024x1536", "auto"):
            kwargs["size"] = size
        else:
            kwargs["size"] = "1024x1024"
        kwargs["quality"] = "high"
        kwargs["output_format"] = "png"
        kwargs["background"] = "opaque"
    else:
        kwargs["prompt"] = prompt[:4000] if "dall-e-3" in m else prompt[:1000]
        kwargs["size"] = size
        kwargs["quality"] = "hd" if "dall-e-3" in m else "standard"
        kwargs["response_format"] = "b64_json"
    resp = client.images.generate(**kwargs)
    b64 = resp.data[0].b64_json
    if not b64:
        raise RuntimeError("images.generate: пустой b64_json")
    out_path.write_bytes(base64.standard_b64decode(b64))

def _floorplan_openai_layout_run(
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
