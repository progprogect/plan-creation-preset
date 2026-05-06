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

def floorplan_openai_overview_image(
    summary_text: str = "",
    output_dir: str = "",
    openai_api_key: str = "",
    image_model: str = "dall-e-3",
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
