from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FormSpec:
    id: str
    title: str
    headers: tuple[str, ...]
    data_headers: tuple[str, ...]
    header_layout: dict[str, Any]
    row_normalization: dict[str, Any]
    header_rows_to_skip: int


def _load_form_specs() -> tuple[str, dict[str, FormSpec]]:
    path = Path(__file__).resolve().parent / "form_structures.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))

    items: dict[str, FormSpec] = {}
    for raw in list(data.get("forms") or []):
        fid = str(raw.get("id") or "").strip().lower()
        if not fid:
            continue
        headers = tuple(str(x) for x in list(raw.get("columns") or []))
        data_headers = tuple(str(x) for x in list(raw.get("data_columns") or [])) or headers
        items[fid] = FormSpec(
            id=fid,
            title=str(raw.get("title") or fid),
            headers=headers,
            data_headers=data_headers,
            header_layout=dict(raw.get("header_layout") or {}),
            row_normalization=dict(raw.get("row_normalization") or {}),
            header_rows_to_skip=int(raw.get("header_rows_to_skip") or 0),
        )

    default = str(data.get("default") or "").strip().lower()
    if not default or default not in items:
        default = next(iter(items.keys()), "form_2_43")
    return default, items


FORM_ENGINE_DEFAULT, FORM_SPECS = _load_form_specs()
FORM_ENGINE_IDS = set(FORM_SPECS.keys())


def normalize_form_type(value: str | None) -> str:
    v = str(value or "").strip().lower()
    return v if v in FORM_ENGINE_IDS else FORM_ENGINE_DEFAULT


def get_form_spec(form_type: str | None) -> FormSpec:
    return FORM_SPECS[normalize_form_type(form_type)]


def list_forms() -> list[dict[str, Any]]:
    return [
        {
            "id": s.id,
            "title": s.title,
            "columns": list(s.headers),
            "data_columns": list(s.data_headers),
            "header_layout": s.header_layout,
            "row_normalization": s.row_normalization,
            "header_rows_to_skip": int(s.header_rows_to_skip),
        }
        for s in FORM_SPECS.values()
    ]
