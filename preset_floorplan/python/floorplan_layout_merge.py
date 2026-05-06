"""
Черновик раскладки (layout_draft) → канонический floorplan_spec v2.
Без сетевых вызовов; используется экспертом merge и OpenAI layout.
"""

from __future__ import annotations

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
