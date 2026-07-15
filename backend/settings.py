from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent


def load_simple_dotenv(path: Path) -> None:
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        val = val.strip()
        if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
            val = val[1:-1]
        os.environ.setdefault(key, val)


def env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, str(default))).strip().lower()
    if raw in ("1", "true", "yes", "y", "on"):
        return True
    if raw in ("0", "false", "no", "n", "off"):
        return False
    return bool(default)


def env_int(name: str, default: int, *, min_value: int = 0) -> int:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        value = int(raw)
    except Exception:
        value = int(default)
    return max(int(min_value), int(value))


def env_float(name: str, default: float, *, min_value: float = 0.0) -> float:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        value = float(raw)
    except Exception:
        value = float(default)
    return max(float(min_value), float(value))


def env_csv(name: str, default_csv: str) -> list[str]:
    raw = str(os.getenv(name, default_csv)).strip()
    return [x.strip() for x in raw.split(",") if x.strip()]

def env_str(name: str, default: str) -> str:
    return str(os.getenv(name, default)).strip()


def _ensure_items(items: list[str], required: list[str]) -> list[str]:
    out = list(items)
    seen = {str(x).strip().lower() for x in out}
    for x in required:
        key = str(x).strip().lower()
        if key and key not in seen:
            out.append(x)
            seen.add(key)
    return out


# Load env files in common project locations.
# Priority: existing OS env vars > production files > local .env files.
for _env_path in (
    ROOT_DIR / ".env.production",
    BASE_DIR / ".env.production",
    ROOT_DIR / ".env",
    BASE_DIR / ".env",
    ROOT_DIR / "frontend" / ".env",
):
    load_simple_dotenv(_env_path)

DATA_DIR = BASE_DIR / "data"
DOCS_DIR = DATA_DIR / "documents"
DB_PATH = DATA_DIR / "portal.db"
PUBLIC_WEB_ORIGIN = env_str("PUBLIC_WEB_ORIGIN", "https://docs.e-qoldau.asia").rstrip("/")
PUBLIC_API_ORIGIN = env_str("PUBLIC_API_ORIGIN", "https://api.e-qoldau.asia").rstrip("/")
BACKEND_HOST = env_str("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT = env_int("BACKEND_PORT", 9000, min_value=1)
CORS_ALLOW_ORIGIN_REGEX = env_str(
    "CORS_ALLOW_ORIGIN_REGEX",
    r"^https://([a-z0-9-]+\.)?e-qoldau\.asia$|^http://(localhost|127\.0\.0\.1)(:\d+)?$",
)

_DEFAULT_CORS_ORIGINS = [
    "https://docs.e-qoldau.asia",
    "https://api.e-qoldau.asia",
    "https://219.e-qoldau.asia",
    "https://243.e-qoldau.asia",
    "https://420.e-qoldau.asia",
    "https://552.e-qoldau.asia",
    "https://analytics.e-qoldau.asia",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
    "http://127.0.0.1:5175",
    "http://localhost:5175",
    "http://127.0.0.1:5176",
    "http://localhost:5176",
    "http://127.0.0.1:5177",
    "http://localhost:5177",
    "http://127.0.0.1:5178",
    "http://localhost:5178",
]

CORS_ORIGINS = _ensure_items(
    env_csv("CORS_ORIGINS", ",".join(_DEFAULT_CORS_ORIGINS)),
    _DEFAULT_CORS_ORIGINS,
)

KEEP_TEMP_ARTIFACTS = env_bool("KEEP_TEMP_ARTIFACTS", True)
HEADER_DEDUP_USE_TEXT_LAYER = env_bool("HEADER_DEDUP_USE_TEXT_LAYER", False)
PROGRESS_MIN_STEP = env_int("PROGRESS_MIN_STEP", 20, min_value=1)
PROGRESS_MIN_INTERVAL_SEC = env_float("PROGRESS_MIN_INTERVAL_SEC", 1.5, min_value=0.1)
STAGE_PROGRESS_MIN_INTERVAL_SEC = env_float("STAGE_PROGRESS_MIN_INTERVAL_SEC", 1.0, min_value=0.1)
WORKER_COUNT = env_int("WORKER_COUNT", 2, min_value=1)
WORKER_IDLE_SLEEP_SEC = env_float("WORKER_IDLE_SLEEP_SEC", 0.5, min_value=0.1)
BATCH_TIMER_ENABLED = env_bool("BATCH_TIMER_ENABLED", False)
OWS_TOKEN = str(os.getenv("OWS_TOKEN", "")).strip()
OWS_BASE_URL = str(os.getenv("OWS_BASE_URL", "https://ows.goszakup.gov.kz")).strip().rstrip("/")

OCR_ENGINE = str(os.getenv("OCR_ENGINE", "pymupdf_text")).strip().lower()
OCR_DEVICE = str(os.getenv("OCR_DEVICE", "auto")).strip().lower()
OCR_LANGUAGES = env_csv("OCR_LANGUAGES", "ru,en,kk")
