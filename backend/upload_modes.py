from __future__ import annotations

from typing import Any

UPLOAD_MODE_PDF_TEXT = "pdf_text"
UPLOAD_MODE_PDF_OCR = "pdf_ocr"

UPLOAD_MODE_DEFAULT = UPLOAD_MODE_PDF_TEXT
UPLOAD_MODE_IDS = {UPLOAD_MODE_PDF_TEXT, UPLOAD_MODE_PDF_OCR}


def normalize_upload_mode(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    return raw if raw in UPLOAD_MODE_IDS else UPLOAD_MODE_DEFAULT


def list_upload_modes() -> list[dict[str, Any]]:
    return [
        {
            "id": UPLOAD_MODE_PDF_TEXT,
            "title": "Обычный PDF",
            "description": "Чтение напрямую из PDF через текстовый слой и табличную структуру.",
        },
        {
            "id": UPLOAD_MODE_PDF_OCR,
            "title": "PDF -> изображения -> OCR",
            "description": "Подготовка растровых страниц для OCR-контура; используется для сканов и сложных PDF.",
        },
    ]
