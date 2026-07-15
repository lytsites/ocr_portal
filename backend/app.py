from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from db import (
    create_document,
    delete_document,
    find_duplicate_doc_id,
    get_analytics_243_filters,
    get_analytics_243_overview,
    get_analytics_243_taxpayer_dynamics,
    get_document,
    get_pipeline_metrics,
    get_report_243,
    get_report_latest,
    init_db,
    list_documents,
    parse_doc_for_api,
    queue_info_for_doc,
)
from form_specs import FORM_ENGINE_DEFAULT, FORM_ENGINE_IDS, get_form_spec, list_forms, normalize_form_type
from ocr_engines import get_ocr_capabilities
from processor import doc_dir, extract_form_meta_from_pdf, extract_header_fingerprint
from settings import CORS_ALLOW_ORIGIN_REGEX, CORS_ORIGINS, DOCUMENT_DELETE_ENABLED, ROOT_DIR
from upload_modes import UPLOAD_MODE_DEFAULT, UPLOAD_MODE_IDS, list_upload_modes, normalize_upload_mode

app = FastAPI(title="PDF Portal Backend", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=CORS_ALLOW_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_name(name: str) -> str:
    keep: list[str] = []
    for ch in name or "":
        if ch.isalnum() or ch in ("-", "_", "."):
            keep.append(ch)
        else:
            keep.append("_")
    return "".join(keep).strip("._") or "upload.pdf"


def _normalized_name_key(name: str) -> str:
    return "".join(ch.lower() for ch in str(name or "") if ch.isalnum())


def _resolve_document_pdf_path(d: dict[str, Any] | None) -> Path | None:
    if not d:
        return None

    stored_path = Path(str(d.get("file_path") or ""))
    if stored_path.exists():
        return stored_path

    forms_dir = ROOT_DIR / "forms"
    if not forms_dir.exists():
        return None

    name = str(d.get("name") or "").strip()
    if name:
        exact = forms_dir / name
        if exact.exists():
            return exact

        expected_key = _normalized_name_key(name)
        for candidate in forms_dir.glob("*.pdf"):
            if _normalized_name_key(candidate.name) == expected_key:
                return candidate

    duplicate_of = str(d.get("duplicate_of") or "").strip()
    if duplicate_of:
        original = get_document(duplicate_of)
        if original:
            return _resolve_document_pdf_path(original)

    return None


def _duration_parts(total_seconds: int) -> tuple[int, int, int]:
    s = max(0, int(total_seconds))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return h, m, sec


def _duration_text(total_seconds: int) -> str:
    h, m, sec = _duration_parts(total_seconds)
    return f"{h} часов, {m} минут, {sec} секунд"


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    return {"ok": True, "time": _now()}


@app.get("/api/forms")
def api_forms() -> dict[str, Any]:
    return {"default": FORM_ENGINE_DEFAULT, "items": list_forms()}


@app.get("/api/ocr/capabilities")
def api_ocr_capabilities() -> dict[str, Any]:
    return get_ocr_capabilities()


@app.get("/api/upload-modes")
def api_upload_modes() -> dict[str, Any]:
    return {"default": UPLOAD_MODE_DEFAULT, "items": list_upload_modes()}


@app.get("/api/config")
def api_config() -> dict[str, Any]:
    return {"document_delete_enabled": bool(DOCUMENT_DELETE_ENABLED)}


@app.get("/api/metrics/pipeline")
def api_pipeline_metrics() -> dict[str, Any]:
    m = get_pipeline_metrics()
    started_at = m.get("started_at")
    finished_at = m.get("finished_at")
    duration_seconds = 0
    if started_at:
        try:
            ts_start = datetime.fromisoformat(str(started_at))
            ts_end = datetime.now() if bool(m.get("active")) else (
                datetime.fromisoformat(str(finished_at)) if finished_at else datetime.now()
            )
            duration_seconds = max(0, int((ts_end - ts_start).total_seconds()))
        except Exception:
            duration_seconds = 0
    pages_total = int(m.get("pages_total") or 0)
    docs_total = int(m.get("docs_total") or 0)
    return {
        "enabled": bool(m.get("enabled")),
        "cycle_id": int(m.get("cycle_id") or 0),
        "active": bool(m.get("active")),
        "started_at": started_at,
        "finished_at": finished_at,
        "pages_total": pages_total,
        "docs_total": docs_total,
        "duration_seconds": duration_seconds,
        "duration_text": _duration_text(duration_seconds),
        "summary_text": f"{pages_total} страниц, {_duration_text(duration_seconds)}",
    }


@app.post("/api/uploads")
async def api_uploads(
    files: list[UploadFile] = File(...),
    dpi: int = Form(300),
    form_type: str = Form(FORM_ENGINE_DEFAULT),
    upload_mode: str = Form(UPLOAD_MODE_DEFAULT),
) -> dict[str, Any]:
    form_raw = str(form_type or "").strip().lower()
    if form_raw and form_raw not in FORM_ENGINE_IDS:
        raise HTTPException(status_code=400, detail=f"Unsupported form_type: {form_type}")
    form_norm = normalize_form_type(form_raw)
    upload_mode_norm = normalize_upload_mode(upload_mode)
    if upload_mode_norm not in UPLOAD_MODE_IDS:
        raise HTTPException(status_code=400, detail=f"Unsupported upload_mode: {upload_mode}")
    created: list[dict[str, Any]] = []
    for upload in files:
        name = _safe_name(upload.filename or "document.pdf")
        content = await upload.read()
        if not content:
            continue
        ext = Path(name).suffix.lower()
        if ext != ".pdf":
            raise HTTPException(status_code=400, detail="Only PDF files are supported in this build")

        doc_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        ddir = doc_dir(doc_id)
        upload_dir = ddir / "upload"
        upload_dir.mkdir(parents=True, exist_ok=True)
        path = upload_dir / name
        path.write_bytes(content)

        try:
            fp = extract_header_fingerprint(path, dpi=int(dpi), content=content)
        except Exception:
            fp = hashlib.sha256(content[:65536]).hexdigest()
        duplicate_of = find_duplicate_doc_id(fp)

        payload = {
            "id": doc_id,
            "name": name,
            "form_type": form_norm,
            "dpi": int(dpi),
            "created_at": _now(),
            "updated_at": _now(),
            "status": "duplicate" if duplicate_of else "queued",
            "stage": "duplicate_detected" if duplicate_of else "waiting_in_queue",
            "file_size_bytes": len(content),
            "file_path": str(path),
            "header_fingerprint": fp,
            "duplicate_of": duplicate_of or "",
            "upload_mode": upload_mode_norm,
            "processing": {
                "status": "skipped" if duplicate_of else "queued",
                "started_at": None,
                "finished_at": None,
                "progress": {"processed": 0, "total": 0, "percent": 0},
                "error": None,
            },
        }
        create_document(payload=payload, queue=not bool(duplicate_of))
        created.append(
            {
                "id": doc_id,
                "name": name,
                "form_type": form_norm,
                "upload_mode": upload_mode_norm,
                "status": "duplicate" if duplicate_of else "queued",
                "duplicate_of": duplicate_of or "",
            }
        )

    if not created:
        raise HTTPException(status_code=400, detail="No files uploaded")
    return {"items": created}


@app.get("/api/documents")
def api_documents() -> dict[str, Any]:
    docs = list_documents()
    items: list[dict[str, Any]] = []
    for d in docs:
        view = parse_doc_for_api(d)
        view["queue"] = queue_info_for_doc(str(view.get("id") or ""))
        items.append(
            {
                "id": view["id"],
                "name": view["name"],
                "form_type": view.get("form_type") or FORM_ENGINE_DEFAULT,
                "upload_mode": view.get("upload_mode") or UPLOAD_MODE_DEFAULT,
                "created_at": view["created_at"],
                "status": view["status"],
                "stage": view["stage"],
                "duplicate_of": view["duplicate_of"] or "",
                "processing": view["processing"],
                "queue": view["queue"],
            }
        )
    return {"items": items}


@app.get("/api/documents/{doc_id}")
def api_document(doc_id: str) -> dict[str, Any]:
    d = get_document(doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="document not found")
    view = parse_doc_for_api(d)
    table_json = doc_dir(doc_id) / "table_results.json"
    if table_json.exists():
        try:
            view["table_result"] = json.loads(table_json.read_text(encoding="utf-8"))
        except Exception:
            view["table_result"] = None
    else:
        view["table_result"] = None
    view["queue"] = queue_info_for_doc(doc_id)
    return view


@app.get("/api/documents/{doc_id}/status")
def api_document_status(doc_id: str) -> dict[str, Any]:
    d = get_document(doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="document not found")
    view = parse_doc_for_api(d)
    return {
        "id": doc_id,
        "status": view.get("status"),
        "stage": view.get("stage"),
        "processing": view.get("processing") or {},
        "queue": queue_info_for_doc(doc_id),
    }


@app.get("/api/documents/{doc_id}/preview")
def api_document_preview(doc_id: str):
    d = get_document(doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="document not found")
    path = _resolve_document_pdf_path(d)
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    safe_name = _safe_name(str(d.get("name") or "document.pdf"))
    return FileResponse(path, media_type="application/pdf", filename=safe_name, headers={"Cache-Control": "no-store"})


@app.delete("/api/documents/{doc_id}")
def api_document_delete(doc_id: str) -> dict[str, Any]:
    if not bool(DOCUMENT_DELETE_ENABLED):
        raise HTTPException(status_code=403, detail="document delete is disabled")
    d = get_document(doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="document not found")
    status = str(d.get("status") or "").strip().lower()
    if status in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="document is still processing")
    try:
        return delete_document(doc_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/documents/{doc_id}/table")
def api_document_table(doc_id: str) -> dict[str, Any]:
    d = get_document(doc_id)
    if not d:
        raise HTTPException(status_code=404, detail="document not found")
    table_json = doc_dir(doc_id) / "table_results.json"
    spec = get_form_spec(str(d.get("form_type") or ""))
    headers = list(spec.data_headers or spec.headers)
    col_count = len(headers)
    if not table_json.exists():
        return {
            "id": doc_id,
            "ready": False,
            "headers": headers,
            "header_layout": spec.header_layout or {},
            "rows": [],
            "row_indent_levels": [],
            "meta": extract_form_meta_from_pdf(_resolve_document_pdf_path(d) or Path(""), str(d.get("form_type") or "")),
        }

    payload = json.loads(table_json.read_text(encoding="utf-8"))
    cells_flat: list[dict[str, Any]] = []
    for page in payload.get("pages") or []:
        page_name = str(page.get("page") or "")
        page_cells = list(page.get("cells") or [])
        page_cells.sort(
            key=lambda c: (int(c.get("row") or 0), int(c.get("col") or 0), int(c.get("cell_id") or 0))
        )
        for cell in page_cells:
            cells_flat.append(
                {
                    "page": page_name,
                    "row": int(cell.get("row") or 0),
                    "col": int(cell.get("col") or 0),
                    "text": str(cell.get("text") or ""),
                    "indent_level": (None if cell.get("indent_level") is None else int(cell.get("indent_level") or 0)),
                }
            )

    by_row: dict[tuple[str, int], list[str]] = {}
    by_row_indent: dict[tuple[str, int], int] = {}
    for c in cells_flat:
        r = int(c.get("row") or 0)
        p = str(c.get("page") or "")
        col = int(c.get("col") or 0)
        if col < 0 or col >= col_count:
            continue
        key = (p, r)
        row_vals = by_row.setdefault(key, [""] * col_count)
        row_vals[col] = str(c.get("text") or "")
        if col == 0 and c.get("indent_level") is not None:
            by_row_indent[key] = int(c.get("indent_level") or 0)

    keys_sorted = sorted(by_row.keys(), key=lambda x: (x[0], x[1]))
    matrix_rows: list[list[str]] = [by_row[k] for k in keys_sorted]
    row_indent_levels: list[int] = [int(by_row_indent.get(k) or 0) for k in keys_sorted]
    return {
        "id": doc_id,
        "ready": True,
        "headers": headers,
        "header_layout": spec.header_layout or {},
        "rows": matrix_rows,
        "row_indent_levels": row_indent_levels,
        "meta": dict(payload.get("meta") or {}) or extract_form_meta_from_pdf(
            _resolve_document_pdf_path(d) or Path(""),
            str(d.get("form_type") or ""),
        ),
    }


@app.get("/api/reports/2-43")
def api_report_243(
    kbk: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    out = get_report_243(kbk=kbk, date_from=date_from, date_to=date_to)
    return {
        "kbk": str(kbk or "").strip(),
        "date_from": date_from,
        "date_to": date_to,
        "summary": out.get("summary") or {},
        "items": out.get("items") or [],
    }


@app.get("/api/reports/{form_type}/latest")
def api_report_latest(form_type: str) -> dict[str, Any]:
    form_raw = str(form_type or "").strip().lower()
    form_norm = form_raw if form_raw.startswith("form_") else f"form_{form_raw.replace('-', '_')}"
    if form_norm not in FORM_ENGINE_IDS:
        raise HTTPException(status_code=400, detail=f"Unsupported form_type: {form_type}")

    out = get_report_latest(form_type=form_norm)
    return {
        "form_type": form_norm,
        "document": out.get("document"),
        "items": out.get("items") or [],
    }


@app.get("/api/analytics/243/filters")
def api_analytics_243_filters() -> dict[str, Any]:
    out = get_analytics_243_filters()
    return {
        "regions": out.get("regions") or [],
        "periods": out.get("periods") or [],
        "kbks": out.get("kbks") or [],
        "banks": out.get("banks") or [],
        "categories": out.get("categories") or [],
        "okeds": out.get("okeds") or [],
        "oked_catalog": out.get("oked_catalog") or [],
        "msb_segments": out.get("msb_segments") or [],
        "periods_by_region": out.get("periods_by_region") or {},
        "kbks_by_region": out.get("kbks_by_region") or {},
        "kbks_by_region_period": out.get("kbks_by_region_period") or {},
    }


@app.get("/api/analytics/243/overview")
def api_analytics_243_overview(
    region: str,
    period: str,
    kbk: str | None = None,
    bank: str | None = None,
    category: str | None = None,
    msb: str | None = None,
    oked: str | None = None,
) -> dict[str, Any]:
    if not str(region or "").strip():
        raise HTTPException(status_code=400, detail="region is required")
    if not str(period or "").strip():
        raise HTTPException(status_code=400, detail="period is required")
    out = get_analytics_243_overview(
        region=region,
        period=period,
        kbk=kbk,
        bank=bank,
        category=category,
        msb=msb,
        oked=oked,
    )
    return out


@app.get("/api/analytics/243/taxpayer-dynamics")
def api_analytics_243_taxpayer_dynamics(
    region: str,
    period: str,
    iin_bin: str | None = None,
    compare_month: str | None = None,
    kbk: str | None = None,
    bank: str | None = None,
    category: str | None = None,
    msb: str | None = None,
    oked: str | None = None,
) -> dict[str, Any]:
    if not str(region or "").strip():
        raise HTTPException(status_code=400, detail="region is required")
    if not str(period or "").strip():
        raise HTTPException(status_code=400, detail="period is required")
    return get_analytics_243_taxpayer_dynamics(
        region=region,
        period=period,
        iin_bin=iin_bin,
        compare_month=compare_month,
        kbk=kbk,
        bank=bank,
        category=category,
        msb=msb,
        oked=oked,
    )
