"""Вызовы OpenAI: Chat (JSON) и сохранение изображения (Images API). Без зависимости от floorplan_core."""

from __future__ import annotations

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
