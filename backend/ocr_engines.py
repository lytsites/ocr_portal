from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
from typing import Any

from settings import OCR_DEVICE, OCR_ENGINE, OCR_LANGUAGES


@dataclass(frozen=True)
class OcrEngineSpec:
    key: str
    title: str
    package_hint: str
    strengths: tuple[str, ...]
    tradeoffs: tuple[str, ...]
    doc_scope: str
    local_module: str | None = None


_ENGINE_SPECS: dict[str, OcrEngineSpec] = {
    "pymupdf_text": OcrEngineSpec(
        key="pymupdf_text",
        title="PyMuPDF text layer",
        package_hint="PyMuPDF",
        strengths=("fastest path for born-digital PDFs", "zero OCR model downloads", "stable extraction of embedded text"),
        tradeoffs=("not real OCR", "weak on scans and rasterized pages"),
        doc_scope="born_digital_pdf",
        local_module="fitz",
    ),
    "paddleocr": OcrEngineSpec(
        key="paddleocr",
        title="PaddleOCR",
        package_hint="paddleocr + paddlepaddle",
        strengths=("strong document OCR", "good CPU and GPU options", "table and structure ecosystem"),
        tradeoffs=("heavier install", "extra runtime setup"),
        doc_scope="scans_and_mixed_docs",
        local_module="paddleocr",
    ),
    "surya": OcrEngineSpec(
        key="surya",
        title="Surya OCR",
        package_hint="surya-ocr + torch",
        strengths=("very strong document OCR", "layout and table-aware stack", "good multilingual coverage"),
        tradeoffs=("heavier inference stack", "best value typically with stronger hardware"),
        doc_scope="document_ocr_and_layout",
        local_module="surya",
    ),
    "doctr": OcrEngineSpec(
        key="doctr",
        title="docTR",
        package_hint="python-doctr + torch or tensorflow",
        strengths=("clean Python integration", "good OCR predictor API", "easy experimentation"),
        tradeoffs=("you tune model choices yourself", "less turnkey than a full document suite"),
        doc_scope="research_and_custom_ocr",
        local_module="doctr",
    ),
}


def _module_available(module_name: str | None) -> bool:
    if not module_name:
        return False
    return find_spec(module_name) is not None


def get_active_ocr_engine_key() -> str:
    return OCR_ENGINE if OCR_ENGINE in _ENGINE_SPECS else "pymupdf_text"


def get_active_ocr_engine_spec() -> OcrEngineSpec:
    return _ENGINE_SPECS[get_active_ocr_engine_key()]


def list_ocr_engines() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    active_key = get_active_ocr_engine_key()
    for key, spec in _ENGINE_SPECS.items():
        items.append(
            {
                "key": spec.key,
                "title": spec.title,
                "package_hint": spec.package_hint,
                "doc_scope": spec.doc_scope,
                "strengths": list(spec.strengths),
                "tradeoffs": list(spec.tradeoffs),
                "available": _module_available(spec.local_module),
                "active": key == active_key,
            }
        )
    return items


def get_ocr_capabilities() -> dict[str, Any]:
    active = get_active_ocr_engine_spec()
    return {
        "active_engine": active.key,
        "active_title": active.title,
        "device": OCR_DEVICE,
        "languages": list(OCR_LANGUAGES),
        "engines": list_ocr_engines(),
        "recommendation_hint": (
            "Use PyMuPDF text layer for born-digital PDFs; switch to PaddleOCR or Surya for scanned PDFs."
        ),
    }
