from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Callable

import fitz

from db import get_document, update_document_fields
from db import replace_report_243_facts, replace_report_552_facts
from form_specs import FORM_ENGINE_DEFAULT, get_form_spec, normalize_form_type
from settings import DOCS_DIR, PROGRESS_MIN_INTERVAL_SEC, PROGRESS_MIN_STEP
from upload_modes import UPLOAD_MODE_DEFAULT, UPLOAD_MODE_PDF_OCR, normalize_upload_mode


def _now() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def doc_dir(doc_id: str) -> Path:
    return DOCS_DIR / doc_id


def _normalize_header_text(text: str) -> str:
    s = (text or "").lower().strip()
    return "".join(ch for ch in s if ch.isalnum())


def _compact_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _find_block(text: str, pattern: str) -> str:
    m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return _compact_space(m.group(1))


def extract_form_meta_from_pdf(input_path: Path, form_type: str) -> dict[str, str]:
    try:
        doc = fitz.open(str(input_path))
    except Exception:
        return {}
    try:
        if len(doc) <= 0:
            return {}
        text = doc[0].get_text("text") or ""
    except Exception:
        text = ""
    finally:
        doc.close()

    if not text.strip():
        return {}

    form = normalize_form_type(form_type)
    if form == "form_2_19":
        return {
            "region": _find_block(text, r"Регион:\s*(.+?)(?:Единица измерения|Специфика|$)"),
            "date": _find_block(text, r"Текущая дата\s*:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})"),
        }

    if form == "form_2_43":
        return {
            "region": _find_block(text, r"Регион:\s*(.+?)(?:Период:|$)"),
            "period": _find_block(text, r"Период:\s*(.+?)(?:Ед\.\s*изм\.|Входящий остаток|$)"),
            "income_code": _find_block(text, r"Код дохода:\s*(.+?)(?:Назначение платежа|$)"),
        }

    if form == "form_4_20":
        return {
            "budget_type": _find_block(text, r"Вид бюджета:\s*(.+?)(?:Месторасположение:|$)"),
            "location": _find_block(text, r"Месторасположение:\s*(.+?)(?:Источник финансирования:|$)"),
            "funding_source": _find_block(text, r"Источник финансирования:\s*(.+?)(?:Администратор Бюджетных программ:|$)"),
            "admin_program": _find_block(text, r"Администратор Бюджетных программ:\s*(.+?)(?:Единица измер|Наименование государственного учреждения:|$)"),
            "institution_name": _find_block(text, r"Наименование государственного учреждения:\s*(.+?)(?:Администратор|План финансирования|$)"),
            "date": _find_block(text, r"на\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})"),
        }

    if form == "form_5_52":
        return {
            "budget_type": _find_block(text, r"Вид бюджета\s*(.+?)(?:Регион|$)"),
            "region": _find_block(text, r"Регион\s*(.+?)(?:Специфика|$)"),
            "specific": _find_block(text, r"Специфика\s*(.+?)(?:Источник финансирования|$)"),
            "funding_source": _find_block(text, r"Источник финансирования\s*(.+?)(?:Дата|$)"),
            "date": _find_block(text, r"Дата\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})"),
        }

    return {}


def extract_header_fingerprint(input_path: Path, dpi: int, *, content: bytes | None = None) -> str:
    # Keep dpi argument for API compatibility.
    _ = dpi
    if input_path.suffix.lower() != ".pdf":
        if content is not None:
            return hashlib.sha256(content[:65536]).hexdigest()
        return hashlib.sha256(input_path.read_bytes()[:65536]).hexdigest()

    try:
        doc = fitz.open(str(input_path))
    except Exception:
        if content is not None:
            return hashlib.sha256(content[:65536]).hexdigest()
        return hashlib.sha256(input_path.read_bytes()[:65536]).hexdigest()

    try:
        if len(doc) <= 0:
            return ""
        text = doc[0].get_text("text") or ""
    except Exception:
        text = ""
    finally:
        doc.close()

    if not text.strip():
        if content is not None:
            return hashlib.sha256(content[:65536]).hexdigest()
        return hashlib.sha256(input_path.read_bytes()[:65536]).hexdigest()
    normalized = _normalize_header_text(text) or text.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()


def _clean_cell(value: Any) -> str:
    s = str(value or "")
    return " ".join(s.split()).strip()


def _row_is_empty(row: list[str]) -> bool:
    return not any(str(x or "").strip() for x in row)


def _header_similarity_score(row: list[str], headers: list[str]) -> int:
    row_norm = ["".join(str(x or "").lower().split()) for x in row]
    hdr_norm = ["".join(str(x or "").lower().split()) for x in headers]
    score = 0
    for idx, val in enumerate(row_norm):
        if idx >= len(hdr_norm):
            break
        hv = hdr_norm[idx]
        if not hv or not val:
            continue
        if hv in val or val in hv:
            score += 1
    return score


def _normalize_row_width(
    row: list[str],
    col_count: int,
    *,
    row_norm: dict[str, Any] | None = None,
    meta: list[dict[str, Any]] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    row_meta = list(meta or [{} for _ in row])
    if len(row) == col_count:
        return row, row_meta
    # Handle known merged-cell patterns where one data cell covers multiple leading columns.
    if len(row) == (col_count - 1):
        hints = list((row_norm or {}).get("insert_empty_after_if_short") or [])
        if hints:
            idx = max(0, int(hints[0]) - 1)
            if idx < len(row):
                return (
                    row[: idx + 1] + [""] + row[idx + 1 :],
                    row_meta[: idx + 1] + [{}] + row_meta[idx + 1 :],
                )
    if len(row) < col_count:
        pad = col_count - len(row)
        return row + [""] * pad, row_meta + ([{}] * pad)
    # Preserve left columns, merge overflow into the last configured column.
    out = row[: col_count - 1]
    out.append(" ".join(x for x in row[col_count - 1 :] if x).strip())
    meta_out = row_meta[: col_count - 1]
    overflow = row_meta[col_count - 1 :]
    # Keep max indent among merged fragments if present.
    indent_vals = [float(m.get("indent_px") or 0.0) for m in overflow if isinstance(m, dict)]
    merged_meta = {"indent_px": (max(indent_vals) if indent_vals else 0.0)}
    meta_out.append(merged_meta)
    return out, meta_out


def _apply_row_normalization(
    row: list[str],
    row_norm: dict[str, Any] | None,
    *,
    meta: list[dict[str, Any]] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    out = list(row or [])
    out_meta = list(meta or [{} for _ in out])
    pairs = list((row_norm or {}).get("merge_columns") or [])
    # Merge configured 1-based column pairs into the first column of the pair.
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        try:
            a = int(pair[0]) - 1
            b = int(pair[1]) - 1
        except Exception:
            continue
        if a < 0 or b <= a or b >= len(out):
            continue
        merged = " ".join(x for x in [str(out[a] or "").strip(), str(out[b] or "").strip()] if x).strip()
        out[a] = merged
        ma = out_meta[a] if a < len(out_meta) else {}
        mb = out_meta[b] if b < len(out_meta) else {}
        indent_px = max(float((ma or {}).get("indent_px") or 0.0), float((mb or {}).get("indent_px") or 0.0))
        if a < len(out_meta):
            out_meta[a] = {"indent_px": indent_px}
        out.pop(b)
        if b < len(out_meta):
            out_meta.pop(b)
    return out, out_meta


def _extract_rows_from_page(page: fitz.Page) -> tuple[list[list[str]], list[list[dict[str, Any]]]]:
    rows: list[list[str]] = []
    metas: list[list[dict[str, Any]]] = []
    try:
        tables = page.find_tables()
    except Exception:
        tables = None

    if tables is not None:
        candidates = list(getattr(tables, "tables", []) or [])
        # Pick the largest table on page.
        candidates.sort(
            key=lambda t: (
                int(getattr(t, "row_count", 0) or 0) * int(getattr(t, "col_count", 0) or 0),
                int(getattr(t, "row_count", 0) or 0),
                int(getattr(t, "col_count", 0) or 0),
            ),
            reverse=True,
        )
        if candidates:
            table = candidates[0]
            # Use cell bboxes to keep left indent metrics.
            for table_row in list(getattr(table, "rows", []) or []):
                row_vals: list[str] = []
                row_meta: list[dict[str, Any]] = []
                for col_idx, bbox in enumerate(list(getattr(table_row, "cells", []) or [])):
                    if not bbox:
                        row_vals.append("")
                        row_meta.append({})
                        continue
                    try:
                        rect = fitz.Rect(bbox)
                        txt = _clean_cell(page.get_text("text", clip=rect) or "")
                    except Exception:
                        txt = ""
                        rect = None
                    meta = {}
                    if col_idx == 0 and rect is not None and txt:
                        try:
                            words = page.get_text("words", clip=rect) or []
                            if words:
                                # Use the first word in reading order for indent.
                                # min(x) over all words is unstable on wrapped lines.
                                words_sorted = sorted(words, key=lambda w: (float(w[1]), float(w[0])))
                                first = words_sorted[0]
                                x_first = float(first[0])
                                meta["indent_px"] = max(0.0, x_first - float(rect.x0))
                            else:
                                meta["indent_px"] = 0.0
                        except Exception:
                            meta["indent_px"] = 0.0
                    row_vals.append(txt)
                    row_meta.append(meta)
                rows.append(row_vals)
                metas.append(row_meta)

    if rows:
        return rows, metas

    # Fallback: line-based extraction when no table grid is detected.
    text = page.get_text("text") or ""
    for line in text.splitlines():
        value = _clean_cell(line)
        if value:
            rows.append([value])
            metas.append([{}])
    return rows, metas


def _indent_level_from_code(text: str) -> int | None:
    m = re.match(r"^\s*(\d{3})\b", str(text or ""))
    if not m:
        return None
    code = m.group(1)
    # 4-20 hierarchy for numeric-leading rows:
    # 356 -> level 0
    # 0xx (except subprogram codes) -> level 1
    # 015, 025, 100, 101 -> level 2
    # all other numeric codes -> level 3
    if code == "356":
        return 0
    if code in {"015", "025", "100", "101"}:
        return 2
    if code.startswith("0"):
        return 1
    return 3


def _normalize_form_243_row(row: list[str]) -> list[str]:
    out = list(row or [])
    if len(out) < 8:
        return out

    # 2) Номер платежного поручения: убрать все пробелы/переносы.
    out[1] = re.sub(r"\s+", "", str(out[1] or ""))

    # 6) ИИК: убрать все пробелы/переносы.
    out[5] = re.sub(r"\s+", "", str(out[5] or ""))

    # 5) Код банка налогоплательщика:
    # убирать пробелы только для SWIFT-подобных кодов (латиница/цифры),
    # чтобы не трогать свободный текст.
    bank_raw = str(out[4] or "")
    bank_nospace = re.sub(r"\s+", "", bank_raw)
    if bank_nospace and re.fullmatch(r"[A-Z0-9]{8,11}", bank_nospace) and re.fullmatch(r"[A-Z0-9\s]+", bank_raw):
        out[4] = bank_nospace

    # Special continuation rows where only cols 4,5,8 are populated:
    # keep 1-4 and 8 as-is, merge 5-7 into col 5.
    c1 = str(out[0] or "").strip()
    c2 = str(out[1] or "").strip()
    c3 = str(out[2] or "").strip()
    c4 = str(out[3] or "").strip()
    c5 = str(out[4] or "").strip()
    c8 = str(out[7] or "").strip()
    if (not c1) and (not c2) and (not c3) and c4 and c5 and c8:
        out[4] = " ".join(x for x in [str(out[4] or "").strip(), str(out[5] or "").strip(), str(out[6] or "").strip()] if x).strip()
        out[5] = ""
        out[6] = ""

    return out


def _rows_from_payload(payload: dict[str, Any], col_count: int) -> list[list[str]]:
    rows: list[list[str]] = []
    for page in list(payload.get("pages") or []):
        cells = list(page.get("cells") or [])
        if not cells:
            continue
        by_row: dict[int, list[str]] = {}
        for c in cells:
            r = int(c.get("row") or 0)
            col = int(c.get("col") or 0)
            if col < 0 or col >= col_count:
                continue
            row_vals = by_row.setdefault(r, [""] * col_count)
            row_vals[col] = str(c.get("text") or "")
        for r_idx in sorted(by_row.keys()):
            row = by_row[r_idx]
            if any(str(x or "").strip() for x in row):
                rows.append(row)
    return rows


def _sync_report_facts(
    doc_id: str,
    form_type: str,
    payload: dict[str, Any],
    *,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> None:
    spec = get_form_spec(form_type)
    col_count = len(spec.data_headers or spec.headers)
    rows = _rows_from_payload(payload, col_count)

    if form_type == "form_2_43":
        facts: list[dict[str, Any]] = []
        for row in rows:
            if len(row) < 8:
                continue
            kbk = str(row[6] or "").strip()
            if not kbk:
                continue
            facts.append(
                {
                    "purpose": str(row[0] or ""),
                    "payment_no": str(row[1] or ""),
                    "row_date": str(row[2] or ""),
                    "iin_bin": str(row[3] or ""),
                    "bank_code": str(row[4] or ""),
                    "iik": str(row[5] or ""),
                    "kbk": kbk,
                    "amount": str(row[7] or ""),
                }
            )
        replace_report_243_facts(doc_id, facts, progress_cb=progress_cb)
        return

    if form_type == "form_5_52":
        facts_552: list[dict[str, Any]] = []
        for row in rows:
            if len(row) < 5:
                continue
            facts_552.append(
                {
                    "fund": str(row[0] or ""),
                    "code_full": str(row[1] or ""),
                    "specific": str(row[2] or ""),
                    "expense_period": str(row[3] or ""),
                    "expense_ytd": str(row[4] or ""),
                }
            )
        replace_report_552_facts(doc_id, facts_552, progress_cb=progress_cb)
        return


def _is_continuation_by_columns(row: list[str], *, allowed_cols: set[int]) -> bool:
    non_empty = [idx for idx, val in enumerate(row) if str(val or "").strip()]
    if not non_empty:
        return False
    return all(idx in allowed_cols for idx in non_empty)


def _merge_continuation_rows(
    rows: list[list[str]],
    metas: list[list[dict[str, Any]]],
    *,
    target_cols: list[int],
) -> tuple[list[list[str]], list[list[dict[str, Any]]]]:
    if not rows:
        return rows, metas

    allowed = {int(c) for c in target_cols if int(c) >= 0}
    out_rows: list[list[str]] = []
    out_metas: list[list[dict[str, Any]]] = []
    for row, meta_row in zip(rows, metas):
        row_vals = list(row)
        meta_vals = list(meta_row)
        if _is_continuation_by_columns(row_vals, allowed_cols=allowed) and out_rows:
            prev = out_rows[-1]
            for col_idx in sorted(allowed):
                prev_txt = str(prev[col_idx] or "").strip() if col_idx < len(prev) else ""
                add_txt = str(row_vals[col_idx] or "").strip() if col_idx < len(row_vals) else ""
                merged = " ".join(x for x in [prev_txt, add_txt] if x).strip()
                if col_idx < len(prev):
                    prev[col_idx] = merged
            continue

        out_rows.append(row_vals)
        out_metas.append(meta_vals)

    return out_rows, out_metas


def _append_to_previous_page_last_row(
    pages_out: list[dict[str, Any]],
    *,
    target_cols: list[int],
    add_row: list[str],
) -> bool:
    if not pages_out:
        return False
    cells = list((pages_out[-1] or {}).get("cells") or [])
    if not cells:
        return False
    targets = {int(c) for c in target_cols if int(c) >= 0}
    last_row_idx = max(int(c.get("row") or 0) for c in cells)
    updated = False
    for c in cells:
        row_idx = int(c.get("row") or 0)
        col_idx = int(c.get("col") or 0)
        if row_idx != last_row_idx or col_idx not in targets:
            continue
        prev_txt = str(c.get("text") or "").strip()
        add_txt = str(add_row[col_idx] or "").strip() if col_idx < len(add_row) else ""
        c["text"] = " ".join(x for x in [prev_txt, add_txt] if x).strip()
        updated = True
    return updated


def extract_table_from_pdf(
    input_path: Path,
    form_type: str,
    *,
    progress_cb: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    spec = get_form_spec(form_type)
    headers = list(spec.data_headers or spec.headers)
    col_count = max(1, len(headers))

    doc = fitz.open(str(input_path))
    pages_total = len(doc)
    if progress_cb:
        progress_cb(0, max(1, pages_total))

    pages_out: list[dict[str, Any]] = []
    cells_total = 0
    cell_seq = 0
    indent_tol_px = float((spec.row_normalization or {}).get("indent_tol_px") or 2.0)
    clusters: list[float] = []

    try:
        for page_idx, page in enumerate(doc):
            raw_rows, raw_metas = _extract_rows_from_page(page)
            norm_rows: list[list[str]] = []
            norm_metas: list[list[dict[str, Any]]] = []
            for r, m in zip(raw_rows, raw_metas):
                r1, m1 = _apply_row_normalization([_clean_cell(v) for v in r], spec.row_normalization, meta=m)
                r2, m2 = _normalize_row_width(r1, col_count, row_norm=spec.row_normalization, meta=m1)
                if spec.id == "form_2_43":
                    r2 = _normalize_form_243_row(r2)
                if _row_is_empty(r2):
                    continue
                norm_rows.append(r2)
                norm_metas.append(m2)

            # Skip known header rows for complex multi-row headers.
            if int(spec.header_rows_to_skip) > 0:
                cut = int(spec.header_rows_to_skip)
                norm_rows = norm_rows[cut:]
                norm_metas = norm_metas[cut:]
            # Otherwise try to drop one repeated header line heuristically.
            elif norm_rows and headers:
                score = _header_similarity_score(norm_rows[0], headers)
                if score >= max(1, min(3, col_count // 2)):
                    norm_rows = norm_rows[1:]
                    norm_metas = norm_metas[1:]

            # Remove visual wraps where a continuation line is extracted as a separate row.
            if spec.id == "form_2_19":
                norm_rows, norm_metas = _merge_continuation_rows(norm_rows, norm_metas, target_cols=[0, 1])
            elif spec.id == "form_4_20":
                norm_rows, norm_metas = _merge_continuation_rows(norm_rows, norm_metas, target_cols=[0])

            # Join wrapped line that spills to the first row of the next page.
            if spec.id in {"form_2_19", "form_4_20"} and norm_rows:
                target_cols = [0, 1] if spec.id == "form_2_19" else [0]
                if _is_continuation_by_columns(norm_rows[0], allowed_cols=set(target_cols)):
                    added = _append_to_previous_page_last_row(
                        pages_out,
                        target_cols=target_cols,
                        add_row=norm_rows[0],
                    )
                    if added:
                        norm_rows = norm_rows[1:]
                        norm_metas = norm_metas[1:]

            # Convert first-column indent (pixels) to discrete levels by clustering
            # real observed offsets on the whole document (not per-page).
            first_col_px = []
            for meta_row, row in zip(norm_metas, norm_rows):
                if row and str(row[0] or "").strip() and meta_row and isinstance(meta_row[0], dict):
                    first_col_px.append(float(meta_row[0].get("indent_px") or 0.0))
            for v in sorted(first_col_px):
                if not clusters:
                    clusters.append(v)
                    continue
                if abs(v - clusters[-1]) <= max(0.1, indent_tol_px):
                    clusters[-1] = (clusters[-1] + v) / 2.0
                else:
                    clusters.append(v)
            if not clusters:
                clusters = [0.0]

            page_name = f"page_{page_idx + 1:04d}"
            page_cells: list[dict[str, Any]] = []
            for r_idx, (row, meta_row) in enumerate(zip(norm_rows, norm_metas)):
                for c_idx in range(col_count):
                    txt = row[c_idx] if c_idx < len(row) else ""
                    cell_meta = meta_row[c_idx] if c_idx < len(meta_row) else {}
                    indent_level = None
                    if c_idx == 0:
                        px = float((cell_meta or {}).get("indent_px") or 0.0)
                        nearest_idx = min(range(len(clusters)), key=lambda i: abs(px - clusters[i]))
                        indent_geo = max(0, int(nearest_idx))
                        indent_level = indent_geo
                        if bool((spec.row_normalization or {}).get("indent_from_code")):
                            indent_code = _indent_level_from_code(txt)
                            if indent_code is not None:
                                indent_level = int(indent_code)
                    page_cells.append(
                        {
                            "cell_id": cell_seq,
                            "row": r_idx,
                            "col": c_idx,
                            "rowspan": 1,
                            "colspan": 1,
                            "text": txt,
                            "indent_level": indent_level,
                        }
                    )
                    cell_seq += 1
                    cells_total += 1

            pages_out.append({"page": page_name, "cells": page_cells})
            if progress_cb:
                progress_cb(page_idx + 1, max(1, pages_total))
    finally:
        doc.close()

    # For form 4-20 keep the final (total) row at top level.
    if spec.id == "form_4_20":
        for page in reversed(pages_out):
            cells = list(page.get("cells") or [])
            if not cells:
                continue
            last_row = max(int(c.get("row") or 0) for c in cells)
            for c in cells:
                if int(c.get("row") or 0) == last_row and int(c.get("col") or 0) == 0:
                    c["indent_level"] = 0
                    break
            break

    return {
        "meta": extract_form_meta_from_pdf(input_path, form_type),
        "pages": pages_out,
        "stats": {
            "pages_total": int(pages_total),
            "cells_total": int(cells_total),
            "cells_target_total": int(cells_total),
        },
    }


def render_pdf_pages_to_images(
    input_path: Path,
    output_dir: Path,
    *,
    dpi: int,
    progress_cb: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(input_path))
    pages_total = len(doc)
    if progress_cb:
        progress_cb(0, max(1, pages_total))
    rendered_files: list[str] = []
    try:
        scale = max(1.0, float(dpi or 300) / 72.0)
        matrix = fitz.Matrix(scale, scale)
        for page_idx, page in enumerate(doc):
            out_path = output_dir / f"page_{page_idx + 1:04d}.png"
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            pix.save(str(out_path))
            rendered_files.append(str(out_path))
            if progress_cb:
                progress_cb(page_idx + 1, max(1, pages_total))
    finally:
        doc.close()
    return {
        "pages_total": int(pages_total),
        "dpi": int(dpi or 300),
        "image_dir": str(output_dir),
        "image_files": rendered_files,
    }


def process_document(doc_id: str) -> None:
    doc = get_document(doc_id)
    if not doc:
        raise RuntimeError(f"document not found: {doc_id}")

    input_path = Path(str(doc.get("file_path") or ""))
    form_type = normalize_form_type(str(doc.get("form_type") or FORM_ENGINE_DEFAULT))
    upload_mode = normalize_upload_mode(doc.get("upload_mode"))
    dpi = int(doc.get("dpi") or 300)
    if not input_path.exists():
        raise RuntimeError(f"input file not found: {input_path}")

    ddir = doc_dir(doc_id)
    table_json_path = ddir / "table_results.json"

    if table_json_path.exists():
        try:
            payload = json.loads(table_json_path.read_text(encoding="utf-8"))
            _sync_report_facts(doc_id, form_type, payload)
            stats = payload.get("stats") or {}
            update_document_fields(
                doc_id,
                status="done",
                stage="completed",
                processing_status="done",
                processing_finished_at=_now(),
                processing_processed=int(stats.get("cells_total") or 0),
                processing_total=int(stats.get("cells_target_total") or 0),
                processing_percent=100,
                processing_stats_json=json.dumps(stats, ensure_ascii=False),
                pages_total=int(stats.get("pages_total") or 0),
                pipeline_out=None,
                cells_dir=None,
            )
            return
        except Exception:
            pass

    update_document_fields(
        doc_id,
        status="processing",
        stage="preparing_document",
        processing_status="processing",
        processing_started_at=_now(),
        processing_finished_at=None,
        processing_processed=0,
        processing_total=0,
        processing_percent=0,
        processing_error=None,
        pipeline_out=json.dumps({"upload_mode": upload_mode}, ensure_ascii=False),
        cells_dir=None,
    )

    pipeline_info: dict[str, Any] = {"upload_mode": upload_mode}
    if upload_mode == UPLOAD_MODE_PDF_OCR:
        ocr_pages_dir = ddir / "ocr_pages"

        def ocr_progress_cb(done: int, total: int) -> None:
            total_safe = max(1, int(total))
            done_safe = max(0, int(done))
            percent = int(round((done_safe * 100) / total_safe))
            update_document_fields(
                doc_id,
                stage=f"rendering_pdf_pages {done_safe}/{total_safe}",
                processing_processed=done_safe,
                processing_total=total_safe,
                processing_percent=min(100, percent),
                pipeline_out=json.dumps(
                    {
                        **pipeline_info,
                        "ocr_preparation": {
                            "status": "rendering_pages",
                            "rendered_pages": done_safe,
                            "pages_total": total_safe,
                        },
                    },
                    ensure_ascii=False,
                ),
            )

        ocr_prep = render_pdf_pages_to_images(input_path, ocr_pages_dir, dpi=dpi, progress_cb=ocr_progress_cb)
        pipeline_info["ocr_preparation"] = {
            "status": "pages_rendered",
            "pages_total": int(ocr_prep.get("pages_total") or 0),
            "dpi": int(ocr_prep.get("dpi") or dpi),
            "image_dir": str(ocr_prep.get("image_dir") or ""),
            "ocr_execution": "pending_integration",
            "current_reading_path": "pdf_text_fallback",
        }
        update_document_fields(
            doc_id,
            stage="ocr_pages_ready",
            pipeline_out=json.dumps(pipeline_info, ensure_ascii=False),
        )

    last_emit = {"processed": -1, "ts": 0.0}

    def progress_cb(done: int, total: int) -> None:
        done_safe = max(0, int(done))
        total_safe = max(1, int(total))
        now_ts = time.time()
        should_emit = (
            done_safe == 0
            or done_safe >= total_safe
            or (done_safe - int(last_emit["processed"])) >= int(PROGRESS_MIN_STEP)
            or (now_ts - float(last_emit["ts"])) >= float(PROGRESS_MIN_INTERVAL_SEC)
        )
        if not should_emit:
            return
        last_emit["processed"] = done_safe
        last_emit["ts"] = now_ts
        percent = int(round((done_safe * 100) / max(1, total_safe)))
        update_document_fields(
            doc_id,
            stage=f"{'reading_pages_ocr_fallback' if upload_mode == UPLOAD_MODE_PDF_OCR else 'reading_pages'} {done_safe}/{total_safe}",
            processing_processed=done_safe,
            processing_total=total_safe,
            processing_percent=min(100, percent),
            pipeline_out=json.dumps(pipeline_info, ensure_ascii=False),
        )

    def sync_progress_cb(done: int, total: int, phase: str) -> None:
        done_safe = max(0, int(done))
        total_safe = max(1, int(total))
        phase_norm = str(phase or "").strip().lower()
        if phase_norm == "cache":
            stage_name = "syncing_facts_cache"
        elif phase_norm == "cache_msb":
            stage_name = "syncing_facts_cache_msb"
        elif phase_norm == "cache_oked":
            stage_name = "syncing_facts_cache_oked"
        elif phase_norm == "rows":
            stage_name = "syncing_facts_rows"
        else:
            stage_name = "syncing_facts"
        percent = int(round((done_safe * 100) / max(1, total_safe)))
        update_document_fields(
            doc_id,
            stage=f"{stage_name} {done_safe}/{total_safe}",
            processing_processed=done_safe,
            processing_total=total_safe,
            processing_percent=min(100, percent),
            pipeline_out=json.dumps(
                {
                    **pipeline_info,
                    "sync_phase": stage_name,
                    "sync_progress": {"processed": done_safe, "total": total_safe, "percent": min(100, percent)},
                },
                ensure_ascii=False,
            ),
        )

    payload = extract_table_from_pdf(input_path, form_type, progress_cb=progress_cb)
    table_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _sync_report_facts(doc_id, form_type, payload, progress_cb=sync_progress_cb)

    stats = payload.get("stats") or {}
    update_document_fields(
        doc_id,
        status="done",
        stage="completed",
        processing_status="done",
        processing_finished_at=_now(),
        processing_processed=int(stats.get("cells_total") or 0),
        processing_total=int(stats.get("cells_target_total") or 0),
        processing_percent=100,
        processing_stats_json=json.dumps(stats, ensure_ascii=False),
        pages_total=int(stats.get("pages_total") or 0),
        pipeline_out=json.dumps(
            {
                **pipeline_info,
                "result": {
                    "status": "done",
                    "table_json_path": str(table_json_path),
                },
            },
            ensure_ascii=False,
        ),
        cells_dir=None,
    )
