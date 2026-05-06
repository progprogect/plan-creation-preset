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
from typing import Any, Dict


def output_dir_path(output_dir: str) -> Path:
    """Каталог для PNG и пр.: пусто → /tmp; пути с ~ раскрываются (Extella Desktop)."""
    s = (output_dir or "").strip()
    if not s:
        return Path("/tmp")
    return Path(s).expanduser()


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
    model: str = "gpt-image-2",
    size: str = "1024x1024",
) -> None:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    m = (model or "gpt-image-2").strip().lower()
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

def floorplan_openai_equipment_images(
    spec_json: str = "",
    output_dir: str = "",
    openai_api_key: str = "",
    image_model: str = "gpt-image-2",
    skip_existing: bool = True,
) -> dict:
    try:
        spec = json.loads(spec_json) if spec_json else {}
    except json.JSONDecodeError as e:
        return {"status": "error", "message": f"invalid_json: {e}", "spec_json": "", "paths": []}
    if spec.get("version") != 2:
        return {"status": "error", "message": "requires_version_2", "spec_json": "", "paths": []}
    odir = output_dir_path(output_dir)
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
