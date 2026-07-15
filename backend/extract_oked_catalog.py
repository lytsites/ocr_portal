from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import fitz

ROOT_DIR = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT_DIR / "oked.pdf"
OUT_JSON = ROOT_DIR / "docs" / "oked-catalog.json"
OUT_CSV = ROOT_DIR / "docs" / "oked-catalog.csv"

CODE_RE = re.compile(r"^(?P<code>\d{2}(?:\.\d+){0,2})\s*(?P<name>.*)$")
KAZAKH_CHARS_RE = re.compile(r"[ӘәҒғҚқҢңӨөҰұҮүІіҺһ]")


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clean_name(value: str) -> str:
    s = normalize_space(value)
    s = re.sub(r"^[\.\-\–\—\:\;,\s]+", "", s)
    return s


def is_noise_line(line: str) -> bool:
    s = normalize_space(line)
    if not s:
        return True
    prefixes = (
        "info@pravosite.kz",
        "© рravosite.kz",
        "© pravosite.kz",
        "коды окэд рк:",
        "коды окэд ",
        "қазақша:",
        "описание раздела",
        "описание секции",
        "информация о классификаторе",
        "полезная информация",
        "общий классификатор",
        "источник:",
        "область применения",
        "дата введения",
        "с изменениями",
        "последние изменения",
    )
    lower = s.lower()
    if lower.startswith(prefixes):
        return True
    if set(s) == {"."}:
        return True
    return False


def line_language_priority(text: str) -> int:
    # Prefer Russian-looking labels to Kazakh for current UI.
    return 0 if KAZAKH_CHARS_RE.search(text or "") else 1


def extract_oked_catalog(pdf_path: Path) -> list[dict[str, str]]:
    doc = fitz.open(str(pdf_path))
    try:
        lines: list[str] = []
        for page in doc:
            lines.extend((page.get_text("text") or "").splitlines())
    finally:
        doc.close()

    cleaned = [normalize_space(x) for x in lines]
    items_by_code: dict[str, dict[str, str | int]] = {}
    order: list[str] = []

    for idx, raw_line in enumerate(cleaned):
        if is_noise_line(raw_line):
            continue
        match = CODE_RE.match(raw_line)
        if not match:
            continue

        code = str(match.group("code") or "").strip()
        name = clean_name(match.group("name") or "")
        if not name:
            for next_idx in range(idx + 1, min(len(cleaned), idx + 4)):
                candidate = cleaned[next_idx]
                if is_noise_line(candidate):
                    continue
                if CODE_RE.match(candidate):
                    break
                name = clean_name(candidate)
                break

        if not code or not name:
            continue

        priority = line_language_priority(name)
        existing = items_by_code.get(code)
        if not existing:
            items_by_code[code] = {"code": code, "name": name, "priority": priority}
            order.append(code)
            continue

        existing_priority = int(existing.get("priority") or 0)
        existing_name = str(existing.get("name") or "")
        should_replace = False
        if priority > existing_priority:
            should_replace = True
        elif priority == existing_priority and len(name) > len(existing_name):
            should_replace = True
        if should_replace:
            items_by_code[code] = {"code": code, "name": name, "priority": priority}

    result: list[dict[str, str]] = []
    for code in order:
        item = items_by_code.get(code)
        if not item:
            continue
        result.append({"code": str(item["code"]), "name": str(item["name"])})
    return result


def main() -> None:
    if not PDF_PATH.exists():
        raise SystemExit(f"PDF not found: {PDF_PATH}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    catalog = extract_oked_catalog(PDF_PATH)
    catalog.sort(key=lambda item: [int(part) for part in str(item["code"]).split(".")])

    OUT_JSON.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["code", "name"])
        writer.writeheader()
        writer.writerows(catalog)

    print(f"Extracted {len(catalog)} OKED entries")
    print(OUT_JSON)
    print(OUT_CSV)


if __name__ == "__main__":
    main()
