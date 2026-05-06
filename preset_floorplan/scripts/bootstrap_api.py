#!/usr/bin/env python3
"""
Публикация пресета в Extella через API.
Использование:
  export EXTELLA_API_TOKEN=...  # заголовок X-Auth-Token

Опционально (если validate не отдаёт контекст):
  export EXTELLA_PROFILE_ID=...
  export EXTELLA_AGENT_ID=...

  python scripts/bootstrap_api.py

Для save/add в заголовках требуются X-Profile-Id и X-Agent-Id; скрипт
подставляет их из /api/token/validate, если не заданы в окружении.

Только POST; не логирует токен.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://api.extella.ai"
ROOT = Path(__file__).resolve().parent.parent


def resolve_context(token: str) -> tuple[str, str]:
    """profile_id и agent_id: из окружения или /api/token/validate."""
    pid = os.environ.get("EXTELLA_PROFILE_ID", "").strip()
    aid = os.environ.get("EXTELLA_AGENT_ID", "").strip()
    if pid and aid:
        return pid, aid
    out = req_raw("POST", "/api/token/validate", token, {"token": token})
    if out.get("status") != "success" or not out.get("valid"):
        raise SystemExit(f"token/validate failed: {out}")
    pid = pid or str(out.get("profile_id") or "")
    aid = aid or str(out.get("agent_id") or "")
    if not pid or not aid:
        raise SystemExit(
            "Не удалось получить profile_id/agent_id. Задайте EXTELLA_PROFILE_ID и EXTELLA_AGENT_ID "
            "или используйте токен, для которого validate возвращает эти поля."
        )
    return pid, aid


def req_raw(method: str, path: str, token: str, body: dict | None = None) -> dict:
    """Запрос без контекста профиля (для token/validate)."""
    url = BASE + path
    data = None
    headers = {"X-Auth-Token": token, "Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {e.code} {path}: {err}") from e


def req(method: str, path: str, token: str, body: dict | None = None, *, profile_id: str, agent_id: str) -> dict:
    url = BASE + path
    data = None
    headers = {
        "X-Auth-Token": token,
        "X-Profile-Id": profile_id,
        "X-Agent-Id": agent_id,
        "Content-Type": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {e.code} {path}: {err}") from e


def save_expert(
    token: str,
    profile_id: str,
    agent_id: str,
    name: str,
    description: str,
    code: str,
    kwargs: dict,
    cspl: str = "fython",
) -> None:
    out = req(
        "POST",
        "/api/expert/save",
        token,
        {"name": name, "description": description, "code": code, "kwargs": kwargs, "cspl": cspl},
        profile_id=profile_id,
        agent_id=agent_id,
    )
    print("save_expert", name, out.get("status"), out.get("expert_name"))


def add_concept(token: str, profile_id: str, agent_id: str, text: str) -> None:
    out = req("POST", "/api/concept/add", token, {"text": text}, profile_id=profile_id, agent_id=agent_id)
    print("concept_add", out.get("id"), out.get("status"))


def main() -> None:
    token = os.environ.get("EXTELLA_API_TOKEN") or os.environ.get("EXTELLA_AUTH_TOKEN")
    if not token:
        print("Задайте EXTELLA_API_TOKEN в окружении.", file=sys.stderr)
        sys.exit(1)

    profile_id, agent_id = resolve_context(token)

    experts_dir = ROOT / "experts"
    specs = [
        {
            "name": "floorplan_build_pipeline",
            "description": (
                "Floor plan preset: validate JSON spec, render SVG, export PDF/PNG. "
                "spec_json: version 1 (schematic) or 2 (equipment, technical_bw, callouts) per "
                "preset_floorplan/schema/floorplan_spec.schema.json; "
                "outputs — comma-separated pdf,png,svg; output_dir (optional); dpi (int); "
                "page_size (A4); orientation (landscape|portrait). "
                "Returns paths, bounding_box, normalized_spec, warnings, errors."
            ),
            "file": experts_dir / "floorplan_build_pipeline.py",
            "kwargs": {
                "spec_json": "",
                "outputs": "pdf,png,svg",
                "output_dir": "",
                "dpi": 150,
                "page_size": "A4",
                "orientation": "landscape",
            },
        },
        {
            "name": "floorplan_spec_validate",
            "description": "Validate and normalize floor plan spec JSON. Params: spec_json (string).",
            "file": experts_dir / "floorplan_spec_validate.py",
            "kwargs": {"spec_json": ""},
        },
        {
            "name": "floorplan_render_svg",
            "description": "Render floor plan spec to SVG file. Params: spec_json, output_dir (optional).",
            "file": experts_dir / "floorplan_render_svg.py",
            "kwargs": {"spec_json": "", "output_dir": ""},
        },
        {
            "name": "floorplan_export_pdf",
            "description": "Convert SVG file to PDF via CairoSVG. Params: svg_path, output_path (optional).",
            "file": experts_dir / "floorplan_export_pdf.py",
            "kwargs": {"svg_path": "", "output_path": ""},
        },
        {
            "name": "floorplan_export_png",
            "description": "Rasterize SVG to PNG via CairoSVG. Params: svg_path, output_path (optional), dpi.",
            "file": experts_dir / "floorplan_export_png.py",
            "kwargs": {"svg_path": "", "output_path": "", "dpi": 150},
        },
    ]

    for s in specs:
        code = s["file"].read_text(encoding="utf-8")
        save_expert(token, profile_id, agent_id, s["name"], s["description"], code, s["kwargs"])

    for md_name in ("master_preset_floorplan.md", "domain_floorplan_geometry_export.md"):
        text = (ROOT / "concepts" / md_name).read_text(encoding="utf-8")
        add_concept(token, profile_id, agent_id, text)


if __name__ == "__main__":
    main()
