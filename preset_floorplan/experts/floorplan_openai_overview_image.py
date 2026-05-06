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

def floorplan_openai_overview_image(
    summary_text: str = "",
    output_dir: str = "",
    openai_api_key: str = "",
    image_model: str = "gpt-image-1.5",
) -> dict:
    if not (summary_text or "").strip():
        return {"status": "error", "message": "summary_text_required", "png_path": None}
    odir = output_dir_path(output_dir)
    odir.mkdir(parents=True, exist_ok=True)
    out = odir / f"floorplan_overview_{uuid.uuid4().hex[:8]}.png"
    try:
        key = resolve_openai_key(openai_api_key)
        prompt = (
            "Industrial facility floor plan from above, technical schematic, black lines on white, "
            "no readable text, orthographic layout illustration:\n"
            + summary_text.strip()[:6000]
        )
        openai_save_image(api_key=key, prompt=prompt, out_path=out, model=str(image_model))
        return {"status": "success", "png_path": str(out.resolve())}
    except Exception as e:
        return {"status": "error", "message": str(e), "png_path": None}
