from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from form_specs import get_form_spec
from processor import extract_table_from_pdf

ROOT_DIR = Path(__file__).resolve().parent.parent
FORMS_DIR = ROOT_DIR / "forms"
REPORTS_DIR = ROOT_DIR / "docs" / "verification"

SAMPLE_FORMS: list[tuple[str, str]] = [
    ("form_2_19", "2-19.pdf"),
    ("form_2_43", "2-43.pdf"),
    ("form_4_20", "4-20.pdf"),
    ("form_5_52", "5-52.pdf"),
]


def _rows_from_page(page: dict[str, Any], col_count: int) -> list[list[str]]:
    cells = list(page.get("cells") or [])
    if not cells:
        return []
    last_row = max(int(c.get("row") or 0) for c in cells)
    rows = [["" for _ in range(col_count)] for _ in range(last_row + 1)]
    for cell in cells:
        row_idx = int(cell.get("row") or 0)
        col_idx = int(cell.get("col") or 0)
        if row_idx < 0 or col_idx < 0 or col_idx >= col_count or row_idx >= len(rows):
            continue
        rows[row_idx][col_idx] = str(cell.get("text") or "").strip()
    return rows


def _non_empty_rows(rows: list[list[str]]) -> list[list[str]]:
    return [row for row in rows if any(str(x or "").strip() for x in row)]


def _preview_rows(rows: list[list[str]], limit: int = 3) -> list[list[str]]:
    out: list[list[str]] = []
    for row in rows[:limit]:
        out.append([str(x or "")[:120] for x in row])
    return out


def _meta_fill_ratio(meta: dict[str, Any]) -> float:
    if not meta:
        return 0.0
    total = len(meta)
    filled = sum(1 for value in meta.values() if str(value or "").strip())
    if total <= 0:
        return 0.0
    return round((filled / total) * 100.0, 1)


def _build_sample_report(form_type: str, file_name: str) -> dict[str, Any]:
    pdf_path = FORMS_DIR / file_name
    spec = get_form_spec(form_type)

    if not pdf_path.exists():
        return {
            "form_type": form_type,
            "title": spec.title,
            "file_name": file_name,
            "exists": False,
            "error": "sample file not found",
        }

    payload = extract_table_from_pdf(pdf_path, form_type)
    pages = list(payload.get("pages") or [])
    meta = dict(payload.get("meta") or {})
    stats = dict(payload.get("stats") or {})
    col_count = len(spec.data_headers or spec.headers)

    total_rows = 0
    page_summaries: list[dict[str, Any]] = []
    sample_preview: list[list[str]] = []

    for idx, page in enumerate(pages, start=1):
        rows = _non_empty_rows(_rows_from_page(page, col_count))
        total_rows += len(rows)
        page_summaries.append(
            {
                "page_index": idx,
                "row_count": len(rows),
                "preview_rows": _preview_rows(rows, limit=2),
            }
        )
        if not sample_preview and rows:
            sample_preview = _preview_rows(rows, limit=3)

    return {
        "form_type": form_type,
        "title": spec.title,
        "file_name": file_name,
        "exists": True,
        "pdf_path": str(pdf_path),
        "headers": list(spec.data_headers or spec.headers),
        "meta": meta,
        "meta_fill_ratio_percent": _meta_fill_ratio(meta),
        "pages_total": int(stats.get("pages_total") or len(pages)),
        "cells_total": int(stats.get("cells_total") or 0),
        "rows_total": int(total_rows),
        "page_summaries": page_summaries,
        "sample_preview_rows": sample_preview,
    }


def _build_markdown(report_items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("# Form sample verification")
    lines.append("")
    lines.append("Автоматический прогон опорных PDF из `forms/` для текущего движка чтения без OCR.")
    lines.append("")
    for item in report_items:
        lines.append(f"## {item['title']} ({item['form_type']})")
        lines.append("")
        if not item.get("exists"):
            lines.append(f"- sample: `{item['file_name']}`")
            lines.append(f"- status: {item.get('error')}")
            lines.append("")
            continue
        lines.append(f"- sample: `{item['file_name']}`")
        lines.append(f"- pages: {item['pages_total']}")
        lines.append(f"- rows: {item['rows_total']}")
        lines.append(f"- cells: {item['cells_total']}")
        lines.append(f"- meta fill: {item['meta_fill_ratio_percent']}%")
        meta = dict(item.get("meta") or {})
        if meta:
            lines.append("- meta:")
            for key, value in meta.items():
                lines.append(f"  - {key}: {value or '-'}")
        preview_rows = list(item.get("sample_preview_rows") or [])
        if preview_rows:
            lines.append("- preview rows:")
            for row in preview_rows:
                lines.append(f"  - {' | '.join(str(x or '-') for x in row)}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_items = [_build_sample_report(form_type, file_name) for form_type, file_name in SAMPLE_FORMS]

    json_path = REPORTS_DIR / "form-samples-report.json"
    md_path = REPORTS_DIR / "form-samples-report.md"

    json_path.write_text(json.dumps({"items": report_items}, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_build_markdown(report_items), encoding="utf-8")

    print(f"[OK] JSON report: {json_path}")
    print(f"[OK] Markdown report: {md_path}")
    for item in report_items:
        status = "missing" if not item.get("exists") else f"pages={item['pages_total']} rows={item['rows_total']}"
        print(f"[FORM] {item['form_type']}: {status}")


if __name__ == "__main__":
    main()
