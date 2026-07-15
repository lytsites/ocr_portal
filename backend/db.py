from __future__ import annotations

import hashlib
import functools
import json
import re
import time
import threading
import shutil
import urllib.parse
import urllib.request
from html import unescape
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

try:
    import pymysql
except Exception:  # pragma: no cover - optional dependency for MySQL mode
    pymysql = None

from settings import (
    BATCH_TIMER_ENABLED,
    DATA_DIR,
    DOCS_DIR,
    DATABASE_ENGINE,
    MYSQL_CHARSET,
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
    OWS_BASE_URL,
    OWS_TOKEN,
    ROOT_DIR,
)
from upload_modes import UPLOAD_MODE_DEFAULT, normalize_upload_mode

DATA_DIR.mkdir(parents=True, exist_ok=True)
DOCS_DIR.mkdir(parents=True, exist_ok=True)

MSB_MICRO = "Микро предпринимательство"
MSB_SMALL = "Малое предпринимательство"
MSB_MEDIUM = "Среднее предпринимательство"
MSB_LARGE = "Крупное предпринимательство"
MSB_SEGMENTS = [MSB_MICRO, MSB_SMALL, MSB_MEDIUM, MSB_LARGE]
MSB_UNKNOWN = "Не определено"
MSB_RSP_SEARCH_URL = "https://rsp.gov.kz/ru/rsp/search?q={iin_bin}"
_MSB_MEMO: dict[str, str] = {}
_MSB_WARMUP_STARTED = False
_MSB_WARMUP_LOCK = threading.Lock()

OKED_UNKNOWN = "Не определено"
OWS_SUBJECT_BIIN_URL = f"{OWS_BASE_URL}/v3/subject/biin/{{iin_bin}}"
_OKED_MEMO: dict[str, tuple[str, str]] = {}
OKED_CATALOG_PATH = ROOT_DIR / "docs" / "oked-catalog.json"
DB_WRITE_RETRY_ATTEMPTS = 6
DB_WRITE_RETRY_BASE_DELAY_SEC = 0.2
DB_ENGINE = str(DATABASE_ENGINE or "mysql").strip().lower()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class _MySQLQueryResult:
    def __init__(self, rows: list[dict[str, Any]], rowcount: int):
        self._rows = rows
        self._rowcount = int(rowcount or 0)
        self._iter_idx = 0

    def fetchone(self) -> dict[str, Any] | None:
        if self._iter_idx >= len(self._rows):
            return None
        row = self._rows[self._iter_idx]
        self._iter_idx += 1
        return dict(row)

    def fetchall(self) -> list[dict[str, Any]]:
        if self._iter_idx >= len(self._rows):
            return []
        out = [dict(r) for r in self._rows[self._iter_idx :]]
        self._iter_idx = len(self._rows)
        return out

    @property
    def rowcount(self) -> int:
        return self._rowcount


class _MySQLEmptyResult:
    rowcount = 0

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[Any]:
        return []


class _MySQLConnection:
    def __init__(self, conn: Any):
        self._conn = conn

    def execute(self, sql: str, params: Any | None = None):
        norm = str(sql or "").strip()
        upper = norm.upper()
        if upper.startswith("PRAGMA"):
            return _MySQLEmptyResult()
        if upper.startswith("COMMIT"):
            self._conn.commit()
            return _MySQLEmptyResult()
        if upper.startswith("ROLLBACK"):
            self._conn.rollback()
            return _MySQLEmptyResult()
        if upper.startswith("BEGIN"):
            with self._conn.cursor() as cursor:
                cursor.execute("START TRANSACTION")
            return _MySQLEmptyResult()

        sql2 = str(sql or "")
        sql2 = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO", "REPLACE INTO", sql2, flags=re.IGNORECASE)
        sql2 = sql2.replace("?", "%s")
        with self._conn.cursor(pymysql.cursors.DictCursor if pymysql else None) as cursor:
            cursor.execute(sql2, params or ())
            if upper.startswith("SELECT") or upper.startswith("SHOW") or upper.startswith("DESCRIBE"):
                rows = list(cursor.fetchall() or [])
                return _MySQLQueryResult(rows, int(getattr(cursor, "rowcount", len(rows)) or len(rows)))
            return _MySQLEmptyResult()

    def close(self) -> None:
        self._conn.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def _connect_mysql() -> _MySQLConnection:
    if pymysql is None:
        raise RuntimeError("PyMySQL is required for DATABASE_ENGINE=mysql. Install backend/requirements.txt.")
    raw = pymysql.connect(
        host=MYSQL_HOST,
        port=int(MYSQL_PORT),
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset=MYSQL_CHARSET,
        autocommit=False,
    )
    return _MySQLConnection(raw)


def _connect_mysql_admin() -> _MySQLConnection:
    if pymysql is None:
        raise RuntimeError("PyMySQL is required for DATABASE_ENGINE=mysql. Install backend/requirements.txt.")
    raw = pymysql.connect(
        host=MYSQL_HOST,
        port=int(MYSQL_PORT),
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        charset=MYSQL_CHARSET,
        autocommit=False,
    )
    return _MySQLConnection(raw)


def _ensure_mysql_database_exists() -> None:
    conn = _connect_mysql_admin()
    try:
        conn.execute(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}` CHARACTER SET {MYSQL_CHARSET}")
        conn.execute("COMMIT")
    finally:
        conn.close()


def _is_db_locked_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        key in text
        for key in (
            "lock wait timeout",
            "deadlock",
            "is locked",
            "can't connect to mysql server during query",
            "server has gone away",
        )
    )


def _run_db_write_with_retry(fn: Callable[[], Any], *, attempts: int = DB_WRITE_RETRY_ATTEMPTS) -> Any:
    last_exc: Exception | None = None
    for attempt in range(max(1, int(attempts))):
        try:
            return fn()
        except Exception as exc:
            if not _is_db_locked_error(exc):
                raise
            last_exc = exc
            if attempt + 1 >= max(1, int(attempts)):
                break
            delay = float(DB_WRITE_RETRY_BASE_DELAY_SEC) * (2**attempt)
            time.sleep(min(delay, 2.5))
    if last_exc is not None:
        raise last_exc
    return None


def get_conn() -> Any:
    if DB_ENGINE != "mysql":
        raise RuntimeError("Only MySQL is supported now. Set DATABASE_ENGINE=mysql and install PyMySQL.")
    return _connect_mysql()


def _init_mysql_db(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
          id VARCHAR(64) PRIMARY KEY,
          name VARCHAR(255) NOT NULL,
          form_type VARCHAR(32) NOT NULL DEFAULT 'form_2_43',
          upload_mode VARCHAR(32) NOT NULL DEFAULT 'pdf_text',
          dpi INT NOT NULL DEFAULT 300,
          created_at VARCHAR(32) NOT NULL,
          updated_at VARCHAR(32) NOT NULL,
          status VARCHAR(32) NOT NULL,
          stage VARCHAR(128) NOT NULL,
          file_size_bytes BIGINT NOT NULL DEFAULT 0,
          file_path TEXT NOT NULL,
          header_fingerprint VARCHAR(128) NOT NULL,
          duplicate_of VARCHAR(64) NOT NULL DEFAULT '',
          processing_status VARCHAR(32) NOT NULL DEFAULT 'queued',
          processing_started_at VARCHAR(32),
          processing_finished_at VARCHAR(32),
          processing_processed INT NOT NULL DEFAULT 0,
          processing_total INT NOT NULL DEFAULT 0,
          processing_percent INT NOT NULL DEFAULT 0,
          processing_error TEXT,
          processing_stats_json LONGTEXT,
          pipeline_out LONGTEXT,
          cells_dir TEXT,
          pages_total INT NOT NULL DEFAULT 0,
          metric_cycle_id INT,
          metric_counted INT NOT NULL DEFAULT 0,
          INDEX idx_docs_created (created_at),
          INDEX idx_docs_status (status),
          INDEX idx_docs_metric_cycle (metric_cycle_id, status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
          id BIGINT AUTO_INCREMENT PRIMARY KEY,
          doc_id VARCHAR(64) NOT NULL UNIQUE,
          priority INT NOT NULL,
          status VARCHAR(32) NOT NULL,
          worker_id VARCHAR(64),
          attempts INT NOT NULL DEFAULT 0,
          created_at VARCHAR(32) NOT NULL,
          started_at VARCHAR(32),
          finished_at VARCHAR(32),
          error LONGTEXT,
          INDEX idx_jobs_status_priority (status, priority, id),
          CONSTRAINT fk_jobs_doc FOREIGN KEY (doc_id) REFERENCES documents(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fingerprints (
          header_fingerprint VARCHAR(128) PRIMARY KEY,
          doc_id VARCHAR(64) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS queue_metrics (
          id INT PRIMARY KEY,
          current_cycle_id INT NOT NULL DEFAULT 0,
          active INT NOT NULL DEFAULT 0,
          started_at VARCHAR(32),
          finished_at VARCHAR(32),
          pages_total INT NOT NULL DEFAULT 0,
          docs_total INT NOT NULL DEFAULT 0
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS report_243_facts (
          id BIGINT AUTO_INCREMENT PRIMARY KEY,
          doc_id VARCHAR(64) NOT NULL,
          row_no INT NOT NULL,
          kbk VARCHAR(32) NOT NULL,
          row_date_iso VARCHAR(32),
          amount DOUBLE,
          payment_no TEXT,
          iin_bin VARCHAR(12),
          msb_segment VARCHAR(64) NOT NULL DEFAULT 'Не определено',
          oked_code VARCHAR(64) NOT NULL DEFAULT 'Не определено',
          oked_name TEXT NOT NULL,
          business_key VARCHAR(64) NOT NULL,
          raw_json LONGTEXT NOT NULL,
          created_at VARCHAR(32) NOT NULL,
          INDEX idx_243_doc (doc_id, row_no),
          INDEX idx_243_kbk_date (kbk, row_date_iso),
          INDEX idx_243_bkey (business_key),
          INDEX idx_243_msb (msb_segment),
          INDEX idx_243_oked (oked_code)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS report_552_facts (
          id BIGINT AUTO_INCREMENT PRIMARY KEY,
          doc_id VARCHAR(64) NOT NULL,
          row_no INT NOT NULL,
          fund TEXT,
          code_full VARCHAR(32),
          administrator TEXT,
          program TEXT,
          subprogram TEXT,
          `specific` TEXT,
          expense_period DOUBLE,
          expense_ytd DOUBLE,
          raw_json LONGTEXT NOT NULL,
          created_at VARCHAR(32) NOT NULL,
          INDEX idx_552_doc (doc_id, row_no)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS msb_registry_cache (
          iin_bin VARCHAR(12) PRIMARY KEY,
          segment VARCHAR(64) NOT NULL,
          checked_at VARCHAR(32) NOT NULL,
          source_url TEXT NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS goszakup_subject_cache (
          iin_bin VARCHAR(12) PRIMARY KEY,
          oked_code VARCHAR(64) NOT NULL,
          oked_name TEXT NOT NULL,
          checked_at VARCHAR(32) NOT NULL,
          source_url TEXT NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _ensure_metrics_row(conn)


def init_db() -> None:
    _ensure_mysql_database_exists()
    conn = get_conn()
    try:
        _init_mysql_db(conn)
    finally:
        conn.close()


def _ensure_column(conn: Any, table: str, column: str, ddl: str) -> None:
    rows = conn.execute(
        """
        SELECT COLUMN_NAME AS name
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
        """,
        (MYSQL_DATABASE, table, column),
    ).fetchall()
    cols = {str(r.get("name") if isinstance(r, dict) else r["name"]) for r in rows}
    if column in cols:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _ensure_metrics_row(conn: Any) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM queue_metrics WHERE id=1").fetchone()
    if row is not None:
        return row
    conn.execute(
        """
        INSERT INTO queue_metrics(id, current_cycle_id, active, started_at, finished_at, pages_total, docs_total)
        VALUES(1, 0, 0, NULL, NULL, 0, 0)
        """
    )
    return conn.execute("SELECT * FROM queue_metrics WHERE id=1").fetchone()


def row_to_dict(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    return dict(row)


def create_document(*, payload: dict[str, Any], queue: bool) -> None:
    now = now_iso()
    conn = get_conn()
    try:
        conn.execute("START TRANSACTION")
        conn.execute(
            """
            INSERT INTO documents (
              id,name,form_type,dpi,created_at,updated_at,status,stage,file_size_bytes,file_path,
              header_fingerprint,duplicate_of,upload_mode,processing_status,processing_started_at,processing_finished_at,
              processing_processed,processing_total,processing_percent,processing_error,processing_stats_json,pipeline_out,cells_dir,
              pages_total,metric_cycle_id,metric_counted
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload["id"],
                payload["name"],
                str(payload.get("form_type") or "form_2_43"),
                int(payload.get("dpi") or 300),
                payload.get("created_at") or now,
                payload.get("updated_at") or now,
                payload.get("status") or "queued",
                payload.get("stage") or "waiting_in_queue",
                int(payload.get("file_size_bytes") or 0),
                payload.get("file_path") or "",
                payload.get("header_fingerprint") or "",
                payload.get("duplicate_of") or "",
                normalize_upload_mode(payload.get("upload_mode")),
                ((payload.get("processing") or {}).get("status") or "queued"),
                ((payload.get("processing") or {}).get("started_at")),
                ((payload.get("processing") or {}).get("finished_at")),
                int((((payload.get("processing") or {}).get("progress") or {}).get("processed") or 0)),
                int((((payload.get("processing") or {}).get("progress") or {}).get("total") or 0)),
                int((((payload.get("processing") or {}).get("progress") or {}).get("percent") or 0)),
                ((payload.get("processing") or {}).get("error")),
                json.dumps(((payload.get("processing") or {}).get("stats") or {}), ensure_ascii=False),
                payload.get("pipeline_out"),
                ((payload.get("dirs") or {}).get("cells") if isinstance(payload.get("dirs"), dict) else None),
                int(payload.get("pages_total") or 0),
                None,
                0,
            ),
        )
        if payload.get("header_fingerprint") and not payload.get("duplicate_of"):
            conn.execute(
                "REPLACE INTO fingerprints(header_fingerprint, doc_id) VALUES(?,?)",
                (payload["header_fingerprint"], payload["id"]),
            )
        if queue:
            if BATCH_TIMER_ENABLED:
                m = _ensure_metrics_row(conn)
                if int(m["active"] or 0) == 1:
                    conn.execute(
                        "UPDATE documents SET metric_cycle_id=?, metric_counted=0 WHERE id=?",
                        (int(m["current_cycle_id"] or 0), payload["id"]),
                    )
            conn.execute(
                "INSERT INTO jobs(doc_id,priority,status,created_at) VALUES(?,?,?,?)",
                (payload["id"], int(payload.get("file_size_bytes") or 0), "queued", now),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def find_duplicate_doc_id(header_fingerprint: str) -> str:
    if not header_fingerprint:
        return ""
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT f.doc_id
            FROM fingerprints f
            JOIN documents d ON d.id = f.doc_id
            WHERE f.header_fingerprint = ? AND d.status != 'deleted'
            LIMIT 1
            """,
            (header_fingerprint,),
        ).fetchone()
        return str(row["doc_id"]) if row else ""
    finally:
        conn.close()


def get_document(doc_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def list_documents() -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
        return [row_to_dict(r) or {} for r in rows]
    finally:
        conn.close()


def delete_document(doc_id: str) -> dict[str, Any]:
    doc = get_document(doc_id)
    if not doc:
        return {"deleted": False, "reason": "not_found"}

    status = str(doc.get("status") or "").strip().lower()
    if status in {"queued", "processing"}:
        raise RuntimeError("cannot_delete_processing_document")

    header_fp = str(doc.get("header_fingerprint") or "").strip()
    doc_root = DOCS_DIR / doc_id
    file_path = Path(str(doc.get("file_path") or "")).resolve(strict=False)

    conn = get_conn()
    try:
        conn.execute("START TRANSACTION")
        conn.execute("DELETE FROM jobs WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM report_243_facts WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM report_552_facts WHERE doc_id=?", (doc_id,))
        if header_fp:
            owner = conn.execute("SELECT doc_id FROM fingerprints WHERE header_fingerprint=?", (header_fp,)).fetchone()
            if owner and str(owner["doc_id"] or "") == doc_id:
                conn.execute("DELETE FROM fingerprints WHERE header_fingerprint=?", (header_fp,))
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()

    try:
        if file_path.exists():
            file_path.unlink()
    except Exception:
        pass
    try:
        if doc_root.exists():
            shutil.rmtree(doc_root, ignore_errors=True)
    except Exception:
        pass
    return {"deleted": True, "id": doc_id}


def update_document_fields(doc_id: str, *, ignore_locked: bool = False, **fields: Any) -> None:
    if not fields:
        return
    fields = dict(fields)
    fields["updated_at"] = now_iso()
    keys = list(fields.keys())
    sql = "UPDATE documents SET " + ", ".join(f"{k}=?" for k in keys) + " WHERE id=?"
    vals = [fields[k] for k in keys] + [doc_id]
    def _write() -> None:
        conn = get_conn()
        try:
            conn.execute(sql, vals)
        finally:
            conn.close()

    try:
        _run_db_write_with_retry(_write)
    except Exception:
        if ignore_locked:
            return
        raise


def set_job_status(doc_id: str, *, status: str, worker_id: str | None = None, error: str | None = None) -> None:
    def _write() -> None:
        conn = get_conn()
        try:
            if status == "processing":
                conn.execute(
                    "UPDATE jobs SET status='processing', worker_id=?, started_at=?, attempts=attempts+1, error=NULL WHERE doc_id=?",
                    (worker_id, now_iso(), doc_id),
                )
            elif status in ("done", "error"):
                conn.execute(
                    "UPDATE jobs SET status=?, finished_at=?, error=? WHERE doc_id=?",
                    (status, now_iso(), error, doc_id),
                )
        finally:
            conn.close()

    _run_db_write_with_retry(_write)


def claim_next_job(worker_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    try:
        conn.execute("START TRANSACTION")
        row = conn.execute(
            """
            SELECT id, doc_id, priority
            FROM jobs
            WHERE status='queued'
            ORDER BY priority ASC, id ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            conn.execute("COMMIT")
            return None
        updated = conn.execute(
            """
            UPDATE jobs
            SET status='processing', worker_id=?, started_at=?, attempts=attempts+1, error=NULL
            WHERE id=? AND status='queued'
            """,
            (worker_id, now_iso(), int(row["id"])),
        ).rowcount
        if updated != 1:
            conn.execute("ROLLBACK")
            return None
        conn.execute("COMMIT")
        return {"id": int(row["id"]), "doc_id": str(row["doc_id"]), "priority": int(row["priority"])}
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def requeue_processing_jobs() -> None:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE jobs SET status='queued', worker_id=NULL, started_at=NULL WHERE status='processing'"
        )
    finally:
        conn.close()


def queue_info_for_doc(doc_id: str) -> dict[str, Any]:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, priority, status FROM jobs WHERE doc_id=? LIMIT 1",
            (doc_id,),
        ).fetchone()
        pending_total = int(
            conn.execute("SELECT COUNT(1) AS c FROM jobs WHERE status='queued'").fetchone()["c"]
        )
        if not row:
            return {"state": "idle", "position": None, "pending_total": pending_total}
        status = str(row["status"])
        if status == "processing":
            return {"state": "processing", "position": 0, "pending_total": pending_total}
        if status != "queued":
            return {"state": "idle", "position": None, "pending_total": pending_total}
        position = int(
            conn.execute(
                """
                SELECT COUNT(1) AS c
                FROM jobs
                WHERE status='queued'
                  AND (priority < ? OR (priority = ? AND id <= ?))
                """,
                (int(row["priority"]), int(row["priority"]), int(row["id"])),
            ).fetchone()["c"]
        )
        return {"state": "queued", "position": position, "pending_total": pending_total}
    finally:
        conn.close()


def mark_doc_processing_start(doc_id: str) -> None:
    if not BATCH_TIMER_ENABLED:
        return
    conn = get_conn()
    try:
        conn.execute("START TRANSACTION")
        m = _ensure_metrics_row(conn)
        cycle_id = int(m["current_cycle_id"] or 0)
        if int(m["active"] or 0) != 1:
            cycle_id += 1
            conn.execute(
                """
                UPDATE queue_metrics
                SET current_cycle_id=?, active=1, started_at=?, finished_at=NULL, pages_total=0, docs_total=0
                WHERE id=1
                """,
                (cycle_id, now_iso()),
            )
        row = conn.execute(
            "SELECT metric_cycle_id FROM documents WHERE id=? LIMIT 1",
            (doc_id,),
        ).fetchone()
        if row is not None and row["metric_cycle_id"] is None:
            conn.execute(
                "UPDATE documents SET metric_cycle_id=?, metric_counted=0 WHERE id=?",
                (cycle_id, doc_id),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def mark_doc_finished_for_metrics(doc_id: str, *, include_pages: bool) -> None:
    if not BATCH_TIMER_ENABLED:
        return
    conn = get_conn()
    try:
        conn.execute("START TRANSACTION")
        m = _ensure_metrics_row(conn)
        current_cycle_id = int(m["current_cycle_id"] or 0)
        doc = conn.execute(
            "SELECT metric_cycle_id, metric_counted, pages_total FROM documents WHERE id=? LIMIT 1",
            (doc_id,),
        ).fetchone()
        if doc is not None and int(doc["metric_cycle_id"] or 0) == current_cycle_id:
            counted = int(doc["metric_counted"] or 0)
            if counted == 0:
                if include_pages:
                    conn.execute(
                        """
                        UPDATE queue_metrics
                        SET pages_total = pages_total + ?, docs_total = docs_total + 1
                        WHERE id=1
                        """,
                        (int(doc["pages_total"] or 0),),
                    )
                conn.execute("UPDATE documents SET metric_counted=1 WHERE id=?", (doc_id,))

        remaining = int(
            conn.execute(
                """
                SELECT COUNT(1) AS c
                FROM documents
                WHERE metric_cycle_id=? AND status IN ('queued','processing')
                """,
                (current_cycle_id,),
            ).fetchone()["c"]
        )
        if int(m["active"] or 0) == 1 and remaining == 0:
            conn.execute(
                "UPDATE queue_metrics SET active=0, finished_at=? WHERE id=1",
                (now_iso(),),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def get_pipeline_metrics() -> dict[str, Any]:
    conn = get_conn()
    try:
        m = _ensure_metrics_row(conn)
        return {
            "enabled": bool(BATCH_TIMER_ENABLED),
            "cycle_id": int(m["current_cycle_id"] or 0),
            "active": bool(int(m["active"] or 0)),
            "started_at": m["started_at"],
            "finished_at": m["finished_at"],
            "pages_total": int(m["pages_total"] or 0),
            "docs_total": int(m["docs_total"] or 0),
        }
    finally:
        conn.close()


def parse_doc_for_api(doc: dict[str, Any]) -> dict[str, Any]:
    stats = {}
    try:
        stats = json.loads(doc.get("processing_stats_json") or "{}")
    except Exception:
        stats = {}
    return {
        "id": doc.get("id"),
        "name": doc.get("name"),
        "form_type": str(doc.get("form_type") or "form_2_43"),
        "upload_mode": normalize_upload_mode(doc.get("upload_mode")),
        "dpi": int(doc.get("dpi") or 300),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "status": doc.get("status"),
        "stage": doc.get("stage"),
        "file_size_bytes": int(doc.get("file_size_bytes") or 0),
        "pages_total": int(doc.get("pages_total") or 0),
        "file_path": doc.get("file_path") or "",
        "header_fingerprint": doc.get("header_fingerprint") or "",
        "duplicate_of": doc.get("duplicate_of") or "",
        "pipeline_out": doc.get("pipeline_out"),
        "dirs": {"cells": doc.get("cells_dir")} if doc.get("cells_dir") else {},
        "processing": {
            "status": doc.get("processing_status") or "queued",
            "started_at": doc.get("processing_started_at"),
            "finished_at": doc.get("processing_finished_at"),
            "progress": {
                "processed": int(doc.get("processing_processed") or 0),
                "total": int(doc.get("processing_total") or 0),
                "percent": int(doc.get("processing_percent") or 0),
            },
            "error": doc.get("processing_error"),
            "stats": stats,
        },
    }


def _parse_date_iso(value: str) -> str | None:
    s = str(value or "").strip()
    if not s:
        return None
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


@functools.lru_cache(maxsize=1)
def load_oked_catalog() -> list[dict[str, str]]:
    if not OKED_CATALOG_PATH.exists():
        return []
    try:
        raw = json.loads(OKED_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[dict[str, str]] = []
    for item in list(raw or []):
        code = str((item or {}).get("code") or "").strip()
        name = str((item or {}).get("name") or "").strip()
        if not code or not name:
            continue
        out.append({"code": code, "name": name})
    return out


def _parse_amount(value: Any) -> float | None:
    s = str(value or "").strip()
    if not s:
        return None
    s = s.replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def _extract_iin_bin(value: str) -> str:
    m = re.search(r"\b(\d{12})\b", str(value or ""))
    return m.group(1) if m else ""


def _norm_key_part(value: Any) -> str:
    return " ".join(str(value or "").split()).strip().lower()


def replace_report_243_facts(
    doc_id: str,
    rows: list[dict[str, Any]],
    *,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> None:
    now = now_iso()
    def _write() -> None:
        conn = get_conn()
        try:
            # Keep the critical path short: use cache-only enrichment here and refresh
            # MSB/OKED caches in the background after the document is already saved.
            iins: list[str] = []
            fallback_abs_by_iin: dict[str, float] = {}
            for row in rows:
                iin_bin = _extract_iin_bin(str(row.get("iin_bin") or ""))
                if not iin_bin:
                    continue
                iins.append(iin_bin)
                fallback_abs_by_iin[iin_bin] = float(fallback_abs_by_iin.get(iin_bin, 0.0) + abs(float(_parse_amount(row.get("amount")) or 0.0)))
            unique_iins = list(dict.fromkeys(iins))
            enrichment_map: dict[str, dict[str, str]] = {}
            for iin in unique_iins:
                msb_segment = _resolve_taxpayer_msb_segment(
                    iin,
                    fallback_total_abs=float(fallback_abs_by_iin.get(iin, 0.0)),
                    allow_network=False,
                )
                oked_code, oked_name = _resolve_taxpayer_oked(iin, allow_network=False)
                enrichment_map[iin] = {
                    "msb_segment": str(msb_segment or MSB_UNKNOWN),
                    "oked_code": str(oked_code or OKED_UNKNOWN),
                    "oked_name": str(oked_name or ""),
                }

            conn.execute("START TRANSACTION")
            conn.execute("DELETE FROM report_243_facts WHERE doc_id=?", (doc_id,))
            total_rows = max(1, len(rows))
            last_emit_ts = 0.0
            for i, row in enumerate(rows):
                kbk = str(row.get("kbk") or "").strip()
                if not kbk:
                    if progress_cb:
                        now_ts = time.time()
                        if i == 0 or (now_ts - last_emit_ts) >= 0.75 or i + 1 >= total_rows:
                            last_emit_ts = now_ts
                            progress_cb(i + 1, total_rows, "rows")
                    continue
                row_date_iso = _parse_date_iso(str(row.get("row_date") or ""))
                amount = _parse_amount(row.get("amount"))
                payment_no = str(row.get("payment_no") or "").strip()
                iin_bin = _extract_iin_bin(str(row.get("iin_bin") or ""))
                enriched = enrichment_map.get(iin_bin) or {"msb_segment": MSB_UNKNOWN, "oked_code": OKED_UNKNOWN, "oked_name": ""}
                bkey_src = "|".join(
                    [
                        _norm_key_part(row_date_iso or row.get("row_date")),
                        _norm_key_part(kbk),
                        _norm_key_part(payment_no),
                        _norm_key_part(iin_bin),
                        _norm_key_part(amount),
                    ]
                )
                business_key = hashlib.sha256(bkey_src.encode("utf-8")).hexdigest()
                conn.execute(
                    """
                    INSERT INTO report_243_facts(
                      doc_id,row_no,kbk,row_date_iso,amount,payment_no,iin_bin,msb_segment,oked_code,oked_name,business_key,raw_json,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        doc_id,
                        i,
                        kbk,
                        row_date_iso,
                        amount,
                        payment_no,
                        iin_bin,
                        str(enriched.get("msb_segment") or MSB_UNKNOWN),
                        str(enriched.get("oked_code") or OKED_UNKNOWN),
                        str(enriched.get("oked_name") or ""),
                        business_key,
                        json.dumps(row, ensure_ascii=False),
                        now,
                    ),
                )
                if progress_cb:
                    now_ts = time.time()
                    if i == 0 or (now_ts - last_emit_ts) >= 0.75 or i + 1 >= total_rows:
                        last_emit_ts = now_ts
                        progress_cb(i + 1, total_rows, "rows")
            conn.execute("COMMIT")
            _start_report_243_enrichment_async(doc_id, unique_iins, fallback_abs_by_iin)
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    _run_db_write_with_retry(_write)


def replace_report_552_facts(
    doc_id: str,
    rows: list[dict[str, Any]],
    *,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> None:
    now = now_iso()
    def _write() -> None:
        conn = get_conn()
        try:
            conn.execute("START TRANSACTION")
            conn.execute("DELETE FROM report_552_facts WHERE doc_id=?", (doc_id,))
            total_rows = max(1, len(rows))
            last_emit_ts = 0.0
            for i, row in enumerate(rows):
                code_full = re.sub(r"\D+", "", str(row.get("code_full") or ""))
                if len(code_full) != 9:
                    if progress_cb:
                        now_ts = time.time()
                        if i == 0 or (now_ts - last_emit_ts) >= 0.75 or i + 1 >= total_rows:
                            last_emit_ts = now_ts
                            progress_cb(i + 1, total_rows, "rows")
                    continue
                admin = code_full[:3]
                program = code_full[3:6]
                subprogram = code_full[6:9]
                conn.execute(
                    """
                    INSERT INTO report_552_facts(
                      doc_id,row_no,fund,code_full,administrator,program,subprogram,`specific`,expense_period,expense_ytd,raw_json,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        doc_id,
                        i,
                        str(row.get("fund") or "").strip(),
                        code_full,
                        admin,
                        program,
                        subprogram,
                        str(row.get("specific") or "").strip(),
                        _parse_amount(row.get("expense_period")),
                        _parse_amount(row.get("expense_ytd")),
                        json.dumps(row, ensure_ascii=False),
                        now,
                    ),
                )
                if progress_cb:
                    now_ts = time.time()
                    if i == 0 or (now_ts - last_emit_ts) >= 0.75 or i + 1 >= total_rows:
                        last_emit_ts = now_ts
                        progress_cb(i + 1, total_rows, "rows")
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    _run_db_write_with_retry(_write)


def get_report_243(*, kbk: str, date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
    kbk_norm = str(kbk or "").strip()
    if not kbk_norm:
        return {"items": [], "summary": {"count": 0, "total_amount": 0.0}}
    params: list[Any] = [kbk_norm]
    where = ["d.status='done'", "d.form_type='form_2_43'", "f.kbk=?"]
    if date_from:
        where.append("f.row_date_iso >= ?")
        params.append(str(date_from))
    if date_to:
        where.append("f.row_date_iso <= ?")
        params.append(str(date_to))
    sql = f"""
        SELECT
          f.doc_id,f.row_no,f.kbk,f.row_date_iso,f.amount,f.payment_no,f.iin_bin,f.msb_segment,f.oked_code,f.oked_name,f.business_key,f.raw_json,
          d.created_at,d.name
        FROM report_243_facts f
        JOIN documents d ON d.id = f.doc_id
        WHERE {' AND '.join(where)}
        ORDER BY d.created_at DESC, f.row_no ASC
    """
    conn = get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    docs_used: set[str] = set()
    for r in rows:
        bkey = str(r["business_key"] or "")
        if bkey in seen:
            continue
        seen.add(bkey)
        docs_used.add(str(r["doc_id"]))
        raw = {}
        try:
            raw = json.loads(str(r["raw_json"] or "{}"))
        except Exception:
            raw = {}
        out.append(
            {
                "doc_id": str(r["doc_id"]),
                "doc_name": str(r["name"] or ""),
                "doc_created_at": str(r["created_at"] or ""),
                "row_no": int(r["row_no"] or 0),
                "kbk": str(r["kbk"] or ""),
                "row_date": str(r["row_date_iso"] or ""),
                "amount": (None if r["amount"] is None else float(r["amount"])),
                "payment_no": str(r["payment_no"] or ""),
                "iin_bin": str(r["iin_bin"] or ""),
                "msb_segment": str(r["msb_segment"] or MSB_UNKNOWN),
                "oked_code": str(r["oked_code"] or OKED_UNKNOWN),
                "oked_name": str(r["oked_name"] or ""),
                "raw": raw,
            }
        )
    total_amount = float(sum(float(x["amount"] or 0.0) for x in out))
    return {
        "items": out,
        "summary": {
            "count": len(out),
            "total_amount": total_amount,
            "docs_used": len(docs_used),
        },
    }


def _normalize_report_form_type(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if raw.startswith("form_"):
        return raw
    return f"form_{raw.replace('-', '_')}"


def _load_latest_table_items(doc_id: str) -> list[dict[str, Any]]:
    table_json = DOCS_DIR / str(doc_id) / "table_results.json"
    if not table_json.exists():
        return []
    try:
        payload = json.loads(table_json.read_text(encoding="utf-8"))
    except Exception:
        return []

    by_key: dict[tuple[str, int], dict[int, str]] = {}
    for page in list(payload.get("pages") or []):
        page_name = str(page.get("page") or "")
        for cell in list(page.get("cells") or []):
            row_no = int(cell.get("row") or 0)
            col_no = int(cell.get("col") or 0)
            if col_no < 0:
                continue
            key = (page_name, row_no)
            row_map = by_key.setdefault(key, {})
            row_map[col_no] = str(cell.get("text") or "")

    keys_sorted = sorted(by_key.keys(), key=lambda x: (x[0], x[1]))
    out: list[dict[str, Any]] = []
    for idx, key in enumerate(keys_sorted):
        page_name, source_row = key
        row_map = by_key.get(key) or {}
        max_col = max(row_map.keys()) if row_map else -1
        cells = [str(row_map.get(i) or "") for i in range(max_col + 1)]
        out.append(
            {
                "row_no": idx,
                "page": page_name,
                "source_row": int(source_row),
                "cells": cells,
                "raw": {"page": page_name, "row": int(source_row), "cells": cells},
            }
        )
    return out


def get_report_latest(*, form_type: str) -> dict[str, Any]:
    form_norm = _normalize_report_form_type(form_type)
    if not form_norm:
        return {"document": None, "items": []}
    supported_forms = {"form_2_19", "form_2_43", "form_4_20", "form_5_52"}
    if form_norm not in supported_forms:
        return {"document": None, "items": []}

    conn = get_conn()
    try:
        d = conn.execute(
            """
            SELECT id,name,created_at
            FROM documents
            WHERE status='done' AND form_type=?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (form_norm,),
        ).fetchone()
        if not d:
            return {"document": None, "items": []}

        rows: list[dict[str, Any]] = []
        if form_norm == "form_5_52":
            rows = conn.execute(
                """
                SELECT row_no,fund,code_full,administrator,program,subprogram,`specific`,expense_period,expense_ytd,raw_json
                FROM report_552_facts
                WHERE doc_id=?
                ORDER BY row_no ASC
                """,
                (str(d["id"]),),
            ).fetchall()
        elif form_norm == "form_2_43":
            rows = conn.execute(
                """
                SELECT row_no,kbk,row_date_iso,amount,payment_no,iin_bin,msb_segment,oked_code,oked_name,raw_json
                FROM report_243_facts
                WHERE doc_id=?
                ORDER BY row_no ASC
                """,
                (str(d["id"]),),
            ).fetchall()
    finally:
        conn.close()

    items: list[dict[str, Any]] = []
    if form_norm == "form_5_52":
        for r in rows:
            raw = {}
            try:
                raw = json.loads(str(r["raw_json"] or "{}"))
            except Exception:
                raw = {}
            items.append(
                {
                    "row_no": int(r["row_no"] or 0),
                    "fund": str(r["fund"] or ""),
                    "code_full": str(r["code_full"] or ""),
                    "administrator": str(r["administrator"] or ""),
                    "program": str(r["program"] or ""),
                    "subprogram": str(r["subprogram"] or ""),
                    "specific": str(r["specific"] or ""),
                    "expense_period": (None if r["expense_period"] is None else float(r["expense_period"])),
                    "expense_ytd": (None if r["expense_ytd"] is None else float(r["expense_ytd"])),
                    "raw": raw,
                }
            )
    elif form_norm == "form_2_43":
        for r in rows:
            raw = {}
            try:
                raw = json.loads(str(r["raw_json"] or "{}"))
            except Exception:
                raw = {}
            items.append(
                {
                    "row_no": int(r["row_no"] or 0),
                    "kbk": str(r["kbk"] or ""),
                    "row_date": str(r["row_date_iso"] or ""),
                    "amount": (None if r["amount"] is None else float(r["amount"])),
                    "payment_no": str(r["payment_no"] or ""),
                    "iin_bin": str(r["iin_bin"] or ""),
                    "msb_segment": str(r["msb_segment"] or MSB_UNKNOWN),
                    "oked_code": str(r["oked_code"] or OKED_UNKNOWN),
                    "oked_name": str(r["oked_name"] or ""),
                    "raw": raw,
                }
            )
    elif form_norm in {"form_2_19", "form_4_20"}:
        # For 2-19 and 4-20 we serve latest parsed table rows from table_results.json.
        items = _load_latest_table_items(str(d["id"]))

    if not items:
        items = _load_latest_table_items(str(d["id"]))

    return {
        "document": {
            "id": str(d["id"]),
            "name": str(d["name"] or ""),
            "created_at": str(d["created_at"] or ""),
            "form_type": form_norm,
        },
        "items": items,
    }


def _extract_yyyy_mm(value: str) -> str:
    s = str(value or "").strip()
    m = re.search(r"^(\d{4})-(\d{2})-\d{2}$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return ""


def _period_prev_year(period_yyyy_mm: str) -> str:
    m = re.search(r"^(\d{4})-(\d{2})$", str(period_yyyy_mm or "").strip())
    if not m:
        return ""
    year = int(m.group(1)) - 1
    return f"{year:04d}-{m.group(2)}"


@functools.lru_cache(maxsize=512)
def _doc_region_cached(doc_id: str) -> str:
    table_json = DOCS_DIR / str(doc_id) / "table_results.json"
    if not table_json.exists():
        return ""
    try:
        payload = json.loads(table_json.read_text(encoding="utf-8"))
    except Exception:
        return ""
    meta = dict(payload.get("meta") or {})
    return str(meta.get("region") or "").strip()


def _counterparty_name(raw: dict[str, Any], iin_bin: str) -> str:
    text = str(raw.get("counterparty") or raw.get("purpose") or raw.get("name") or "").strip()
    if not text:
        return str(iin_bin or "").strip() or "РќРµ СѓРєР°Р·Р°РЅ"
    s = " ".join(text.split())
    iin = str(iin_bin or "").strip()
    if iin:
        s = s.replace(iin, " ")
    s = re.sub(r"^\s*(?:РРРќ|Р‘РРќ|IIN|BIN)\s*[:\-]?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^\s*\d{12}\s*", "", s)
    s = re.sub(r"\s+", " ", s).strip(" ,.;:-")
    return s or (iin if iin else "РќРµ СѓРєР°Р·Р°РЅ")


def _clean_iin_taxpayer_field(value: Any) -> str:
    s = " ".join(str(value or "").split()).strip()
    if not s:
        return ""
    s = re.sub(r"^\s*(?:РРРќ|Р‘РРќ|IIN|BIN)\s*[:\-]?\s*", "", s, flags=re.IGNORECASE)
    return s.strip(" ,.;:-")


def _classify_tax_category(kbk: str, purpose: str) -> str:
    kbk_norm = str(kbk or "").strip()
    purpose_norm = str(purpose or "").lower()
    if kbk_norm.startswith("101") or "подоход" in purpose_norm or "ипн" in purpose_norm:
        return "Подоходный налог"
    if kbk_norm.startswith("102") or "социаль" in purpose_norm:
        return "Социальные платежи"
    if kbk_norm.startswith("103") or "ндс" in purpose_norm:
        return "НДС"
    if kbk_norm.startswith("104") or "имуществ" in purpose_norm:
        return "Налог на имущество"
    if kbk_norm.startswith("105") or "зем" in purpose_norm:
        return "Земельный налог"
    if kbk_norm.startswith("106") or "транспорт" in purpose_norm:
        return "Транспортный налог"
    return "Прочие налоги"


def _classify_budget_category(kbk: str, purpose: str) -> str:
    kbk_norm = str(kbk or "").strip()
    purpose_norm = str(purpose or "").lower()
    if kbk_norm.startswith(("1", "2")):
        return "Налоговые"
    if kbk_norm.startswith("3") or "штраф" in purpose_norm or "пени" in purpose_norm:
        return "Неналоговые"
    if kbk_norm.startswith(("4", "5")) or "продаж" in purpose_norm:
        return "Доходы от продажи основного капитала"
    return "Налоговые"


def _classify_oked_proxy(kbk: str, purpose: str) -> str:
    kbk_norm = str(kbk or "").strip()
    purpose_norm = str(purpose or "").lower()
    if kbk_norm.startswith("104") or "имуществ" in purpose_norm:
        return "L68 Недвижимость (proxy)"
    if kbk_norm.startswith("105") or "зем" in purpose_norm:
        return "A01 С/Х и землепользование (proxy)"
    if kbk_norm.startswith("106") or "транспорт" in purpose_norm:
        return "H49 Транспорт (proxy)"
    if kbk_norm.startswith("103") or "ндс" in purpose_norm:
        return "G47 Торговля (proxy)"
    if kbk_norm.startswith("101") or "подоход" in purpose_norm or "ипн" in purpose_norm:
        return "M69 Профуслуги (proxy)"
    return "Не определен (proxy)"


def _classify_msb_segment_by_amount(total_amount_abs: float) -> str:
    value = abs(float(total_amount_abs or 0.0))
    if value < 15_000_000:
        return MSB_MICRO
    if value < 100_000_000:
        return MSB_SMALL
    if value < 300_000_000:
        return MSB_MEDIUM
    return MSB_LARGE


def _msb_group(segment: str) -> str:
    s = str(segment or "").strip()
    if s == MSB_LARGE:
        return "Крупный бизнес"
    if s in (MSB_MICRO, MSB_SMALL, MSB_MEDIUM):
        return "МСБ"
    return MSB_UNKNOWN


def _normalize_iin_bin(value: str) -> str:
    src = str(value or "").strip()
    if not src:
        return ""
    m = re.search(r"(?<!\d)(\d{12})(?!\d)", src)
    if m:
        return str(m.group(1))
    digits = re.sub(r"\D+", "", src)
    if len(digits) == 12:
        return digits
    return ""


def _normalize_msb_filter(msb: str | None) -> tuple[str, str]:
    raw = str(msb or "").strip()
    if not raw:
        return ("", "")
    if raw in (MSB_SEGMENTS + [MSB_UNKNOWN]):
        return (raw, "")
    if raw in ("МСБ", "Крупный бизнес"):
        return ("", raw)
    return ("", "")


def _msb_from_text(page_text: str) -> str | None:
    text = str(page_text or "")
    if not text:
        return None
    text_lower = text.lower()
    for category in MSB_SEGMENTS:
        if category.lower() in text_lower:
            return category
    return None


def _load_msb_cached(iin_bin: str) -> str | None:
    if not iin_bin:
        return None
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT segment FROM msb_registry_cache WHERE iin_bin=?",
            (iin_bin,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    segment = str(row["segment"] or "").strip()
    return segment if segment in MSB_SEGMENTS else None


def _save_msb_cached(iin_bin: str, segment: str, source_url: str) -> None:
    if not iin_bin or segment not in MSB_SEGMENTS:
        return
    def _write() -> None:
        conn = get_conn()
        try:
            conn.execute(
                """
                INSERT INTO msb_registry_cache(iin_bin, segment, checked_at, source_url)
                VALUES(?,?,?,?)
                ON DUPLICATE KEY UPDATE
                  segment=VALUES(segment),
                  checked_at=VALUES(checked_at),
                  source_url=VALUES(source_url)
                """,
                (iin_bin, segment, now_iso(), str(source_url or "")),
            )
        finally:
            conn.close()

    _run_db_write_with_retry(_write)


def _load_oked_cached(iin_bin: str) -> tuple[str, str] | None:
    if not iin_bin:
        return None
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT oked_code, oked_name FROM goszakup_subject_cache WHERE iin_bin=?",
            (iin_bin,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    code = str(row["oked_code"] or "").strip() or OKED_UNKNOWN
    name = str(row["oked_name"] or "").strip()
    return (code, name)


def _save_oked_cached(iin_bin: str, oked_code: str, oked_name: str, source_url: str) -> None:
    if not iin_bin:
        return
    code = str(oked_code or "").strip() or OKED_UNKNOWN
    name = str(oked_name or "").strip()
    def _write() -> None:
        conn = get_conn()
        try:
            conn.execute(
                """
                INSERT INTO goszakup_subject_cache(iin_bin, oked_code, oked_name, checked_at, source_url)
                VALUES(?,?,?,?,?)
                ON DUPLICATE KEY UPDATE
                  oked_code=VALUES(oked_code),
                  oked_name=VALUES(oked_name),
                  checked_at=VALUES(checked_at),
                  source_url=VALUES(source_url)
                """,
                (iin_bin, code, name, now_iso(), str(source_url or "")),
            )
        finally:
            conn.close()

    _run_db_write_with_retry(_write)


def _extract_single_oked_entry(item: Any) -> tuple[str, str]:
    if isinstance(item, dict):
        code = str(item.get("code") or item.get("oked") or item.get("value") or item.get("id") or "").strip()
        name = str(item.get("name") or item.get("title") or item.get("label") or "").strip()
        return (code, name)
    if item is None:
        return ("", "")
    if isinstance(item, (str, int, float)):
        return (str(item).strip(), "")
    return ("", "")


def _extract_oked_from_subject_payload(payload: Any) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return (OKED_UNKNOWN, "")

    codes: list[str] = []
    names: list[str] = []
    seen_codes: set[str] = set()
    seen_names: set[str] = set()

    def add_entry(code: str, name: str) -> None:
        code_norm = str(code or "").strip()
        name_norm = str(name or "").strip()
        if code_norm and code_norm not in seen_codes:
            seen_codes.add(code_norm)
            codes.append(code_norm)
        if name_norm and name_norm not in seen_names:
            seen_names.add(name_norm)
            names.append(name_norm)

    oked_list = payload.get("oked_list")
    if isinstance(oked_list, list):
        for item in oked_list:
            code, name = _extract_single_oked_entry(item)
            add_entry(code, name)
    elif oked_list is not None:
        code, name = _extract_single_oked_entry(oked_list)
        add_entry(code, name)

    add_entry(str(payload.get("oked") or payload.get("main_oked") or "").strip(), str(payload.get("oked_name") or payload.get("main_oked_name") or "").strip())

    code_out = ", ".join(codes) if codes else OKED_UNKNOWN
    name_out = " | ".join(names)
    return (code_out, name_out)


def _fetch_oked_from_goszakup(iin_bin: str) -> tuple[str, str, str]:
    if not iin_bin:
        return (OKED_UNKNOWN, "", "")
    url = OWS_SUBJECT_BIIN_URL.format(iin_bin=urllib.parse.quote(iin_bin))
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Accept-Language": "ru-RU,ru;q=0.9",
    }
    if OWS_TOKEN:
        headers["Authorization"] = f"Bearer {OWS_TOKEN}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
        payload = json.loads(body or "{}")
    except Exception:
        return (OKED_UNKNOWN, "", url)
    code, name = _extract_oked_from_subject_payload(payload)
    return (code or OKED_UNKNOWN, name, url)


def _fetch_msb_from_rsp(iin_bin: str) -> tuple[str | None, str]:
    if not iin_bin:
        return (None, "")
    url = MSB_RSP_SEARCH_URL.format(iin_bin=urllib.parse.quote(iin_bin))
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "ru-RU,ru;q=0.9",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return (None, url)
    # Lightweight HTML -> text normalization for keyword matching.
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"\s+", " ", text).strip()
    return (_msb_from_text(text), url)


def _resolve_taxpayer_msb_segment(
    iin_bin: str,
    *,
    fallback_total_abs: float = 0.0,
    allow_network: bool = False,
) -> str:
    norm_iin = _normalize_iin_bin(iin_bin)
    if not norm_iin:
        return _classify_msb_segment_by_amount(fallback_total_abs) if fallback_total_abs else MSB_UNKNOWN
    if norm_iin in _MSB_MEMO:
        return _MSB_MEMO[norm_iin]

    cached = _load_msb_cached(norm_iin)
    if cached:
        _MSB_MEMO[norm_iin] = cached
        return cached

    if allow_network:
        resolved, source_url = _fetch_msb_from_rsp(norm_iin)
        if resolved:
            _save_msb_cached(norm_iin, resolved, source_url)
            _MSB_MEMO[norm_iin] = resolved
            return resolved

    return _classify_msb_segment_by_amount(fallback_total_abs) if fallback_total_abs else MSB_UNKNOWN


def _resolve_taxpayer_oked(
    iin_bin: str,
    *,
    allow_network: bool = False,
) -> tuple[str, str]:
    norm_iin = _normalize_iin_bin(iin_bin)
    if not norm_iin:
        return (OKED_UNKNOWN, "")
    if norm_iin in _OKED_MEMO:
        return _OKED_MEMO[norm_iin]
    cached = _load_oked_cached(norm_iin)
    if cached:
        _OKED_MEMO[norm_iin] = cached
        return cached
    if allow_network:
        code, name, source_url = _fetch_oked_from_goszakup(norm_iin)
        _save_oked_cached(norm_iin, code, name, source_url)
        resolved = (code or OKED_UNKNOWN, name)
        _OKED_MEMO[norm_iin] = resolved
        return resolved
    return (OKED_UNKNOWN, "")


def _warm_msb_cache_for_keys(
    iin_keys: list[str],
    *,
    max_to_fetch: int = 120,
    progress_cb: Callable[[int, int], None] | None = None,
) -> None:
    if max_to_fetch <= 0:
        return
    seen: set[str] = set()
    pending: list[str] = []
    for raw in iin_keys:
        norm = _normalize_iin_bin(raw)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        if norm in _MSB_MEMO:
            continue
        if _load_msb_cached(norm):
            continue
        pending.append(norm)
        if len(pending) >= max_to_fetch:
            break
    total = len(pending)
    for idx, norm in enumerate(pending):
        resolved, source_url = _fetch_msb_from_rsp(norm)
        if resolved:
            _save_msb_cached(norm, resolved, source_url)
            _MSB_MEMO[norm] = resolved
        if progress_cb:
            progress_cb(idx + 1, total)


def _warm_oked_cache_for_keys(
    iin_keys: list[str],
    *,
    max_to_fetch: int = 120,
    progress_cb: Callable[[int, int], None] | None = None,
) -> None:
    if max_to_fetch <= 0:
        return
    seen: set[str] = set()
    pending: list[str] = []
    for raw in iin_keys:
        norm = _normalize_iin_bin(raw)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        if norm in _OKED_MEMO:
            continue
        if _load_oked_cached(norm):
            continue
        pending.append(norm)
        if len(pending) >= max_to_fetch:
            break
    total = len(pending)
    for idx, norm in enumerate(pending):
        code, name, source_url = _fetch_oked_from_goszakup(norm)
        _save_oked_cached(norm, code, name, source_url)
        _OKED_MEMO[norm] = (code or OKED_UNKNOWN, name)
        if progress_cb:
            progress_cb(idx + 1, total)


def _start_msb_warmup_async(iin_keys: list[str]) -> None:
    global _MSB_WARMUP_STARTED
    if _MSB_WARMUP_STARTED:
        return
    with _MSB_WARMUP_LOCK:
        if _MSB_WARMUP_STARTED:
            return
        _MSB_WARMUP_STARTED = True
    unique_keys = list(dict.fromkeys([k for k in iin_keys if _normalize_iin_bin(k)]))

    def _worker() -> None:
        try:
            _warm_msb_cache_for_keys(unique_keys, max_to_fetch=len(unique_keys))
        finally:
            global _MSB_WARMUP_STARTED
            with _MSB_WARMUP_LOCK:
                _MSB_WARMUP_STARTED = False

    t = threading.Thread(target=_worker, name="msb-cache-warmup", daemon=True)
    t.start()


def _start_report_243_enrichment_async(doc_id: str, iin_keys: list[str], fallback_abs_by_iin: dict[str, float]) -> None:
    unique_keys = list(dict.fromkeys([_normalize_iin_bin(k) for k in iin_keys if _normalize_iin_bin(k)]))
    if not unique_keys:
        return

    def _worker() -> None:
        try:
            _warm_msb_cache_for_keys(unique_keys, max_to_fetch=len(unique_keys))
            _warm_oked_cache_for_keys(unique_keys, max_to_fetch=len(unique_keys))

            conn = get_conn()
            try:
                rows = conn.execute(
                    "SELECT row_no, iin_bin, amount FROM report_243_facts WHERE doc_id=?",
                    (doc_id,),
                ).fetchall()
            finally:
                conn.close()

            if not rows:
                return

            conn = get_conn()
            try:
                conn.execute("START TRANSACTION")
                for r in rows:
                    row_no = int(r["row_no"] or 0)
                    iin_bin = _normalize_iin_bin(str(r["iin_bin"] or ""))
                    fallback_total_abs = float(fallback_abs_by_iin.get(iin_bin, 0.0))
                    msb_segment = _resolve_taxpayer_msb_segment(
                        iin_bin,
                        fallback_total_abs=fallback_total_abs,
                        allow_network=False,
                    )
                    oked_code, oked_name = _resolve_taxpayer_oked(iin_bin, allow_network=False)
                    conn.execute(
                        """
                        UPDATE report_243_facts
                        SET msb_segment=?, oked_code=?, oked_name=?
                        WHERE doc_id=? AND row_no=?
                        """,
                        (
                            str(msb_segment or MSB_UNKNOWN),
                            str(oked_code or OKED_UNKNOWN),
                            str(oked_name or ""),
                            doc_id,
                            row_no,
                        ),
                    )
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                conn.close()
        except Exception:
            # Background enrichment is best-effort only.
            return

    t = threading.Thread(target=_worker, name=f"report-243-enrich-{doc_id}", daemon=True)
    t.start()


def _split_iin_name(text_value: str, fallback_iin: str) -> tuple[str, str]:
    src = " ".join(str(text_value or "").split()).strip()
    fallback = str(fallback_iin or "").strip()
    iin_match = re.search(r"\b(\d{12})\b", src)
    iin = iin_match.group(1) if iin_match else fallback
    name = src
    if iin:
        name = name.replace(iin, " ")
    name = re.sub(r"(?i)\b(?:иин|бин|iin|bin)\b\s*[:\-]?", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" ,.;:-")
    return (iin, (name or iin or "Не указан"))


def _is_243_merged_row_from_raw(raw: dict[str, Any]) -> bool:
    c0 = str(raw.get("purpose") or "").strip()
    c1 = str(raw.get("payment_no") or "").strip()
    c2 = str(raw.get("row_date") or "").strip()
    c3 = str(raw.get("iin_bin") or "").strip()
    c4 = str(raw.get("bank_code") or "").strip()
    c5 = str(raw.get("iik") or "").strip()
    c6 = str(raw.get("kbk") or "").strip()
    c7 = str(raw.get("amount") or "").strip()
    if c0 or c1 or c2:
        return False
    if not c3 or not c4:
        return False
    amount_in7 = bool(c7)
    amount_in5 = bool(_parse_amount(c5)) and not c7
    return (not c6) and (amount_in7 or amount_in5)


def _is_243_complete_row(raw: dict[str, Any]) -> bool:
    required = [
        str(raw.get("purpose") or "").strip(),
        str(raw.get("payment_no") or "").strip(),
        str(raw.get("row_date") or "").strip(),
        str(raw.get("iin_bin") or "").strip(),
        str(raw.get("bank_code") or "").strip(),
        str(raw.get("iik") or "").strip(),
        str(raw.get("kbk") or "").strip(),
        str(raw.get("amount") or "").strip(),
    ]
    return all(required)


def get_analytics_243_filters() -> dict[str, Any]:
    rows = _load_analytics_243_rows()
    oked_catalog = load_oked_catalog()
    warm_keys: list[str] = []
    regions_set: set[str] = set()
    periods_set: set[str] = set()
    kbks_set: set[str] = set()
    banks_set: set[str] = set()
    categories_set: set[str] = set()
    oked_set: set[str] = set()
    periods_by_region_set: dict[str, set[str]] = {}
    kbks_by_region_set: dict[str, set[str]] = {}
    kbks_by_region_period_set: dict[str, dict[str, set[str]]] = {}

    for x in rows:
        if not bool(x.get("is_complete")):
            continue
        if bool(x.get("is_merged")):
            continue
        region = str(x.get("region") or "").strip()
        period = str(x.get("period") or "").strip()
        kbk = str(x.get("kbk") or "").strip()
        bank_code = str(x.get("bank_code") or "").strip()
        category = str(x.get("category_bucket") or "").strip()
        oked = str(x.get("oked_proxy") or "").strip()
        if not region or not period or not kbk:
            continue
        tax_key = str(x.get("iin_bin") or "").strip() or str(x.get("counterparty_iin_field") or "").strip()
        if tax_key:
            warm_keys.append(tax_key)
        regions_set.add(region)
        periods_set.add(period)
        kbks_set.add(kbk)
        if bank_code:
            banks_set.add(bank_code)
        if category:
            categories_set.add(category)
        if oked:
            oked_set.add(oked)
        periods_by_region_set.setdefault(region, set()).add(period)
        kbks_by_region_set.setdefault(region, set()).add(kbk)
        kbks_by_region_period_set.setdefault(region, {}).setdefault(period, set()).add(kbk)

    periods_by_region = {k: sorted(v, reverse=True) for k, v in periods_by_region_set.items()}
    kbks_by_region = {k: sorted(v) for k, v in kbks_by_region_set.items()}
    kbks_by_region_period = {
        region: {period: sorted(kbks) for period, kbks in per_map.items()}
        for region, per_map in kbks_by_region_period_set.items()
    }
    # Start background warmup so MSB filter has data before active use.
    _start_msb_warmup_async(warm_keys)

    return {
        "regions": sorted(regions_set),
        "periods": sorted(periods_set, reverse=True),
        "kbks": sorted(kbks_set),
        "banks": sorted(banks_set),
        "categories": sorted(categories_set),
        "okeds": sorted(oked_set | {OKED_UNKNOWN}),
        "oked_catalog": oked_catalog,
        "msb_segments": MSB_SEGMENTS + [MSB_UNKNOWN],
        "periods_by_region": periods_by_region,
        "kbks_by_region": kbks_by_region,
        "kbks_by_region_period": kbks_by_region_period,
    }


def _load_analytics_243_rows() -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT
              f.doc_id,f.row_no,f.kbk,f.row_date_iso,f.amount,f.payment_no,f.iin_bin,f.msb_segment,f.oked_code,f.oked_name,f.business_key,f.raw_json,
              d.created_at
            FROM report_243_facts f
            JOIN documents d ON d.id = f.doc_id
            WHERE d.status='done' AND d.form_type='form_2_43'
            ORDER BY d.created_at DESC, f.row_no ASC
            """
        ).fetchall()
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        bkey = str(r["business_key"] or "")
        if not bkey or bkey in seen:
            continue
        seen.add(bkey)
        raw = {}
        try:
            raw = json.loads(str(r["raw_json"] or "{}"))
        except Exception:
            raw = {}
        row_period = _extract_yyyy_mm(str(r["row_date_iso"] or ""))
        if not row_period:
            continue
        raw_iin_text = _clean_iin_taxpayer_field(raw.get("iin_bin"))
        bank_code = str(raw.get("bank_code") or "").strip()
        purpose = str(raw.get("purpose") or "").strip()
        kbk = str(r["kbk"] or "").strip()
        category = _classify_tax_category(kbk, purpose)
        category_bucket = _classify_budget_category(kbk, purpose)
        oked_code = str(r["oked_code"] or "").strip() or OKED_UNKNOWN
        oked_name = str(r["oked_name"] or "").strip()
        oked_proxy = oked_code if oked_code else OKED_UNKNOWN
        out.append(
            {
                "doc_id": str(r["doc_id"]),
                "region": _doc_region_cached(str(r["doc_id"])),
                "kbk": kbk,
                "row_date": str(r["row_date_iso"] or ""),
                "period": row_period,
                "amount": float(r["amount"] or 0.0),
                "iin_bin": str(r["iin_bin"] or "").strip(),
                "counterparty_iin_field": (raw_iin_text or str(r["iin_bin"] or "").strip() or "РќРµ СѓРєР°Р·Р°РЅ"),
                "bank_code": bank_code,
                "purpose": purpose,
                "category": category,
                "category_bucket": category_bucket,
                "oked_proxy": oked_proxy,
                "oked_name": oked_name,
                "msb_segment": str(r["msb_segment"] or "").strip() or MSB_UNKNOWN,
                "is_complete": bool(_is_243_complete_row(raw)),
                "is_merged": bool(_is_243_merged_row_from_raw(raw)),
            }
        )
    return out


def get_analytics_243_overview(
    *,
    region: str,
    period: str,
    kbk: str | None = None,
    bank: str | None = None,
    category: str | None = None,
    msb: str | None = None,
    oked: str | None = None,
) -> dict[str, Any]:
    region_norm = str(region or "").strip()
    period_norm = str(period or "").strip()
    is_all_periods = period_norm in ("all", "__all__")
    if not region_norm or (not is_all_periods and not re.match(r"^\d{4}-\d{2}$", period_norm)):
        return {
            "filters": {"region": region_norm, "period": period_norm, "kbk": str(kbk or "").strip()},
            "kpi": {
                "total_amount": 0.0,
                "yoy_percent": None,
                "unique_taxpayers": 0,
                "top10_share_percent": 0.0,
                "top10_amount": 0.0,
                "operations_count": 0,
                "avg_ticket": 0.0,
            },
            "series_monthly": [],
            "series_msb_monthly": [],
            "top10": [],
            "top20": [],
            "by_bank": [],
            "by_category": [],
            "msb_breakdown": [],
            "by_oked": [],
            "oked_table": [],
            "msb_top10": [],
            "summary_by_kbk": [],
            "summary_by_category": [],
            "top_analytics": [],
        }

    kbk_norm = str(kbk or "").strip()
    bank_norm = str(bank or "").strip()
    category_norm = str(category or "").strip()
    msb_exact, msb_group_filter = _normalize_msb_filter(msb)
    oked_norm = str(oked or "").strip()
    all_rows = _load_analytics_243_rows()
    scoped_rows = [
        x for x in all_rows
        if str(x.get("region") or "") == region_norm
        and (not kbk_norm or str(x.get("kbk") or "") == kbk_norm)
        and (not bank_norm or str(x.get("bank_code") or "") == bank_norm)
        and (not category_norm or str(x.get("category_bucket") or "") == category_norm)
        and (not oked_norm or str(x.get("oked_proxy") or "") == oked_norm)
    ]
    period_scoped = scoped_rows if is_all_periods else [x for x in scoped_rows if x["period"] == period_norm]

    taxpayer_totals_abs: dict[str, float] = {}
    taxpayer_segment_from_rows: dict[str, str] = {}
    for x in period_scoped:
        tax_key = str(x.get("iin_bin") or "").strip() or str(x.get("counterparty_iin_field") or "").strip()
        if not tax_key:
            continue
        taxpayer_totals_abs[tax_key] = float(taxpayer_totals_abs.get(tax_key, 0.0) + abs(float(x.get("amount") or 0.0)))
        seg = str(x.get("msb_segment") or "").strip()
        if seg:
            taxpayer_segment_from_rows[tax_key] = seg
    if msb_exact:
        _warm_msb_cache_for_keys(list(taxpayer_totals_abs.keys()), max_to_fetch=40)
    taxpayer_segment: dict[str, str] = {
        key: (taxpayer_segment_from_rows.get(key) or _resolve_taxpayer_msb_segment(
            key,
            fallback_total_abs=float(total_abs or 0.0),
            allow_network=False,
        ))
        for key, total_abs in taxpayer_totals_abs.items()
    }
    if msb_exact or msb_group_filter:
        deduped = []
        for x in period_scoped:
            tax_key = str(x.get("iin_bin") or "").strip() or str(x.get("counterparty_iin_field") or "").strip()
            seg_value = str(taxpayer_segment.get(tax_key, MSB_UNKNOWN) or "").strip()
            if msb_exact and seg_value == msb_exact:
                deduped.append(x)
                continue
            if msb_group_filter and _msb_group(seg_value) == msb_group_filter:
                deduped.append(x)
    else:
        deduped = period_scoped

    period_rows = deduped
    prev_rows: list[dict[str, Any]] = []
    if not is_all_periods:
        prev_period = _period_prev_year(period_norm)
        prev_rows = [x for x in scoped_rows if x["period"] == prev_period]

    total_amount = float(sum(float(x["amount"] or 0.0) for x in period_rows))
    prev_total = float(sum(float(x["amount"] or 0.0) for x in prev_rows))
    yoy_percent: float | None = None
    if (not is_all_periods) and prev_total > 0:
        yoy_percent = ((total_amount - prev_total) / prev_total) * 100.0

    unique_taxpayers = len({str(x["iin_bin"] or "").strip() for x in period_rows if str(x["iin_bin"] or "").strip()})
    operations_count = len(period_rows)
    avg_ticket = (total_amount / operations_count) if operations_count > 0 else 0.0

    by_month: dict[str, float] = {}
    by_month_msb: dict[str, float] = {}
    by_month_non_msb: dict[str, float] = {}
    for x in scoped_rows:
        period_key = str(x.get("period") or "").strip()
        amount = float(x.get("amount") or 0.0)
        by_month[period_key] = float(by_month.get(period_key, 0.0) + amount)
        tax_key = str(x.get("iin_bin") or "").strip() or str(x.get("counterparty_iin_field") or "").strip()
        if _msb_group(taxpayer_segment.get(tax_key, MSB_UNKNOWN)) == "МСБ":
            by_month_msb[period_key] = float(by_month_msb.get(period_key, 0.0) + amount)
        else:
            by_month_non_msb[period_key] = float(by_month_non_msb.get(period_key, 0.0) + amount)
    monthly_keys = sorted(by_month.keys())
    if not is_all_periods:
        monthly_keys = [k for k in monthly_keys if k <= period_norm]
    monthly_keys = monthly_keys[-12:]
    series_monthly = [{"period": k, "amount": float(by_month[k])} for k in monthly_keys]
    series_msb_monthly = [
        {
            "period": k,
            "msb_amount": float(by_month_msb.get(k, 0.0)),
            "non_msb_amount": float(by_month_non_msb.get(k, 0.0)),
        }
        for k in monthly_keys
    ]

    by_counterparty: dict[str, dict[str, Any]] = {}
    for x in period_rows:
        if not bool(x.get("is_complete")):
            continue
        if bool(x.get("is_merged")):
            continue
        key = str(x["counterparty_iin_field"] or "").strip() or "Не указан"
        node = by_counterparty.setdefault(
            key,
            {"counterparty": key, "amount": 0.0, "tax_ids": set(), "kbks": set()},
        )
        node["amount"] = float(node["amount"]) + float(x["amount"] or 0.0)
        if str(x["iin_bin"] or "").strip():
            node["tax_ids"].add(str(x["iin_bin"]))
        if str(x["kbk"] or "").strip():
            node["kbks"].add(str(x["kbk"]))

    ranked = sorted(by_counterparty.values(), key=lambda z: float(z["amount"] or 0.0), reverse=True)
    top20 = [
        {
            "counterparty": str(x["counterparty"] or ""),
            "amount": float(x["amount"] or 0.0),
            "taxpayer_ids": sorted(list(x["tax_ids"])),
            "kbks": sorted(list(x["kbks"])),
        }
        for x in ranked[:20]
    ]
    top10 = top20[:10]
    top10_amount = float(sum(float(x["amount"] or 0.0) for x in top10))
    top10_share_percent = (top10_amount / total_amount * 100.0) if total_amount > 0 else 0.0
    cr10_percent = top10_share_percent

    by_bank_map: dict[str, float] = {}
    by_category_map: dict[str, float] = {}
    by_oked_map: dict[str, float] = {}
    by_oked_taxpayers: dict[str, set[str]] = {}
    msb_breakdown_map: dict[str, dict[str, float]] = {}
    for x in period_rows:
        amount = float(x.get("amount") or 0.0)
        bank_code = str(x.get("bank_code") or "").strip() or "Не указан"
        by_bank_map[bank_code] = float(by_bank_map.get(bank_code, 0.0) + amount)
        cat = str(x.get("category_bucket") or "").strip() or "Налоговые"
        by_category_map[cat] = float(by_category_map.get(cat, 0.0) + amount)
        oked_key = str(x.get("oked_proxy") or "").strip() or "Не определен (proxy)"
        by_oked_map[oked_key] = float(by_oked_map.get(oked_key, 0.0) + amount)
        tax_key = str(x.get("iin_bin") or "").strip() or str(x.get("counterparty_iin_field") or "").strip()
        if tax_key:
            by_oked_taxpayers.setdefault(oked_key, set()).add(tax_key)
        segment = taxpayer_segment.get(tax_key, MSB_UNKNOWN)
        node = msb_breakdown_map.setdefault(segment, {"amount": 0.0, "taxpayers": set()})
        node["amount"] = float(node["amount"]) + amount
        if tax_key:
            node["taxpayers"].add(tax_key)

    by_bank = [
        {"name": k, "amount": float(v)}
        for k, v in sorted(by_bank_map.items(), key=lambda t: float(t[1]), reverse=True)[:12]
    ]
    by_category = [
        {"name": k, "amount": float(v)}
        for k, v in sorted(by_category_map.items(), key=lambda t: float(t[1]), reverse=True)
    ]
    by_oked = [
        {"name": k, "amount": float(v)}
        for k, v in sorted(by_oked_map.items(), key=lambda t: float(t[1]), reverse=True)[:12]
    ]
    msb_breakdown: list[dict[str, Any]] = []
    for segment in MSB_SEGMENTS:
        node = msb_breakdown_map.get(segment) or {"amount": 0.0, "taxpayers": set()}
        amount = float(node.get("amount") or 0.0)
        taxpayers = node.get("taxpayers") or set()
        msb_breakdown.append(
            {
                "segment": segment,
                "amount": amount,
                "taxpayers": len(taxpayers),
                "share_percent": ((amount / total_amount) * 100.0) if total_amount else 0.0,
            }
        )

    msb_amount = float(
        sum(
            float(x.get("amount") or 0.0)
            for x in period_rows
            if _msb_group(taxpayer_segment.get(str(x.get("iin_bin") or "").strip() or str(x.get("counterparty_iin_field") or "").strip(), MSB_UNKNOWN)) == "МСБ"
        )
    )
    msb_share_percent = (msb_amount / total_amount * 100.0) if total_amount else 0.0

    prev_by_tax: dict[str, float] = {}
    for x in prev_rows:
        tax_key = str(x.get("iin_bin") or "").strip() or str(x.get("counterparty_iin_field") or "").strip()
        if not tax_key:
            continue
        prev_by_tax[tax_key] = float(prev_by_tax.get(tax_key, 0.0) + float(x.get("amount") or 0.0))

    top_analytics: list[dict[str, Any]] = []
    for idx, x in enumerate(ranked[:20], start=1):
        tax_ids = sorted(list(x["tax_ids"]))
        iin_bin = tax_ids[0] if tax_ids else ""
        parsed_iin, parsed_name = _split_iin_name(str(x["counterparty"] or ""), iin_bin)
        cur_amount = float(x["amount"] or 0.0)
        prev_amount = float(prev_by_tax.get(parsed_iin or iin_bin, 0.0))
        change_percent = None
        if prev_amount > 0:
            change_percent = ((cur_amount - prev_amount) / prev_amount) * 100.0
        top_analytics.append(
            {
                "rank": idx,
                "iin_bin": parsed_iin or iin_bin or "-",
                "name": parsed_name,
                "amount": cur_amount,
                "share_percent": ((cur_amount / total_amount) * 100.0) if total_amount else 0.0,
                "change_percent": change_percent,
            }
        )

    summary_by_kbk_map: dict[str, float] = {}
    summary_by_cat_map: dict[str, float] = {}
    for x in period_rows:
        kbk_key = str(x.get("kbk") or "").strip() or "-"
        summary_by_kbk_map[kbk_key] = float(summary_by_kbk_map.get(kbk_key, 0.0) + float(x.get("amount") or 0.0))
        cat_key = str(x.get("category_bucket") or "").strip() or "Налоговые"
        summary_by_cat_map[cat_key] = float(summary_by_cat_map.get(cat_key, 0.0) + float(x.get("amount") or 0.0))
    summary_by_kbk = [
        {
            "name": k,
            "amount": float(v),
            "share_percent": ((float(v) / total_amount) * 100.0) if total_amount else 0.0,
        }
        for k, v in sorted(summary_by_kbk_map.items(), key=lambda t: float(t[1]), reverse=True)
    ]
    summary_by_category = [
        {
            "name": k,
            "amount": float(v),
            "share_percent": ((float(v) / total_amount) * 100.0) if total_amount else 0.0,
        }
        for k, v in sorted(summary_by_cat_map.items(), key=lambda t: float(t[1]), reverse=True)
    ]

    msb_top10_raw: list[dict[str, Any]] = []
    for x in top_analytics:
        seg = _msb_group(taxpayer_segment.get(str(x.get("iin_bin") or "").strip(), MSB_UNKNOWN))
        if seg == "МСБ":
            msb_top10_raw.append(x)
    msb_top10 = msb_top10_raw[:10]

    oked_table = []
    for idx, x in enumerate(by_oked, start=1):
        raw = str(x.get("name") or "")
        parts = [p.strip() for p in raw.split(" - ", 1)]
        if len(parts) == 2 and parts[0]:
            oked_code, oked_name = parts[0], parts[1]
        else:
            oked_code, oked_name = raw or OKED_UNKNOWN, raw or OKED_UNKNOWN
        oked_table.append(
            {
                "rank": idx,
                "oked": oked_code,
                "name": oked_name,
                "amount": float(x.get("amount") or 0.0),
                "share_percent": ((float(x.get("amount") or 0.0) / total_amount) * 100.0) if total_amount else 0.0,
                "taxpayers": len(by_oked_taxpayers.get(raw, set())),
            }
        )

    return {
        "filters": {
            "region": region_norm,
            "period": period_norm,
            "kbk": kbk_norm,
            "bank": bank_norm,
            "category": category_norm,
            "msb": msb_exact or msb_group_filter,
            "oked": oked_norm,
        },
        "kpi": {
            "total_amount": total_amount,
            "prev_total_amount": prev_total,
            "yoy_percent": yoy_percent,
            "unique_taxpayers": unique_taxpayers,
            "top10_share_percent": top10_share_percent,
            "top10_amount": top10_amount,
            "msb_share_percent": msb_share_percent,
            "cr10_percent": cr10_percent,
            "operations_count": operations_count,
            "avg_ticket": avg_ticket,
        },
        "series_monthly": series_monthly,
        "series_msb_monthly": series_msb_monthly,
        "top10": top10,
        "top20": top20,
        "by_bank": by_bank,
        "by_category": by_category,
        "msb_breakdown": msb_breakdown,
        "by_oked": by_oked,
        "summary_by_kbk": summary_by_kbk,
        "summary_by_category": summary_by_category,
        "top_analytics": top_analytics,
        "msb_top10": msb_top10,
        "oked_table": oked_table,
        "meta": {"oked_note": "ОКЭД рассчитан как proxy по КБК и назначению платежа."},
    }


def _filter_analytics_243_rows(
    *,
    region: str,
    kbk: str | None = None,
    bank: str | None = None,
    category: str | None = None,
    oked: str | None = None,
) -> list[dict[str, Any]]:
    region_norm = str(region or "").strip()
    kbk_norm = str(kbk or "").strip()
    bank_norm = str(bank or "").strip()
    category_norm = str(category or "").strip()
    oked_norm = str(oked or "").strip()
    rows = _load_analytics_243_rows()
    return [
        x for x in rows
        if str(x.get("region") or "").strip() == region_norm
        and (not kbk_norm or str(x.get("kbk") or "").strip() == kbk_norm)
        and (not bank_norm or str(x.get("bank_code") or "").strip() == bank_norm)
        and (not category_norm or str(x.get("category_bucket") or "").strip() == category_norm)
        and (not oked_norm or str(x.get("oked_proxy") or "").strip() == oked_norm)
    ]


def _period_to_quarter(period_yyyy_mm: str) -> str:
    m = re.match(r"^(\d{4})-(\d{2})$", str(period_yyyy_mm or "").strip())
    if not m:
        return ""
    month = int(m.group(2))
    quarter = ((month - 1) // 3) + 1
    return f"{m.group(1)}-Q{quarter}"


def get_analytics_243_taxpayer_dynamics(
    *,
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
    region_norm = str(region or "").strip()
    period_norm = str(period or "").strip()
    is_all_periods = period_norm in ("all", "__all__")
    if not region_norm or (not is_all_periods and not re.match(r"^\d{4}-\d{2}$", period_norm)):
        return {
            "filters": {"region": region_norm, "period": period_norm},
            "taxpayers": [],
            "selected_taxpayer": None,
            "available_months": [],
            "series_monthly": [],
            "series_quarterly": [],
            "compare_month": None,
            "series_year_compare": [],
            "kbk_structure": [],
            "seasonality": None,
            "profile": None,
            "comparison_table": {
                "year": None,
                "monthly_rows": [],
                "quarterly_rows": [],
                "aggregated_rows": [],
            },
        }

    scoped_rows = _filter_analytics_243_rows(region=region_norm, kbk=kbk, bank=bank, category=category, oked=oked)
    period_scoped = scoped_rows if is_all_periods else [x for x in scoped_rows if str(x.get("period") or "").strip() == period_norm]

    taxpayer_totals_abs: dict[str, float] = {}
    taxpayer_segment_from_rows: dict[str, str] = {}
    for x in period_scoped:
        tax_key = str(x.get("iin_bin") or "").strip() or str(x.get("counterparty_iin_field") or "").strip()
        if not tax_key:
            continue
        taxpayer_totals_abs[tax_key] = float(taxpayer_totals_abs.get(tax_key, 0.0) + abs(float(x.get("amount") or 0.0)))
        seg = str(x.get("msb_segment") or "").strip()
        if seg:
            taxpayer_segment_from_rows[tax_key] = seg
    msb_exact, msb_group_filter = _normalize_msb_filter(msb)
    if msb_exact:
        _warm_msb_cache_for_keys(list(taxpayer_totals_abs.keys()), max_to_fetch=40)
    taxpayer_segment = {
        key: (taxpayer_segment_from_rows.get(key) or _resolve_taxpayer_msb_segment(
            key,
            fallback_total_abs=float(total_abs or 0.0),
            allow_network=False,
        ))
        for key, total_abs in taxpayer_totals_abs.items()
    }
    if msb_exact or msb_group_filter:
        allowed_tax_keys = {
            key for key, segment in taxpayer_segment.items()
            if (
                (msb_exact and str(segment or "").strip() == msb_exact)
                or (msb_group_filter and _msb_group(str(segment or "").strip()) == msb_group_filter)
            )
        }
        scoped_rows = [
            x for x in scoped_rows
            if (str(x.get("iin_bin") or "").strip() or str(x.get("counterparty_iin_field") or "").strip()) in allowed_tax_keys
        ]

    clean_rows = [x for x in scoped_rows if bool(x.get("is_complete")) and not bool(x.get("is_merged"))]
    by_taxpayer: dict[str, dict[str, Any]] = {}
    for x in clean_rows:
        raw_iin = str(x.get("iin_bin") or "").strip()
        tax_key = raw_iin or str(x.get("counterparty_iin_field") or "").strip()
        if not tax_key:
            continue
        parsed_iin, parsed_name = _split_iin_name(str(x.get("counterparty_iin_field") or ""), raw_iin)
        key = parsed_iin or tax_key
        node = by_taxpayer.setdefault(
            key,
            {"iin_bin": key, "name": parsed_name, "total_amount": 0.0, "monthly": {}},
        )
        period_key = str(x.get("period") or "").strip()
        amount = float(x.get("amount") or 0.0)
        node["total_amount"] = float(node["total_amount"]) + amount
        node["monthly"][period_key] = float(node["monthly"].get(period_key, 0.0) + amount)

    taxpayers = sorted(by_taxpayer.values(), key=lambda item: float(item.get("total_amount") or 0.0), reverse=True)
    taxpayer_list = [
        {
            "iin_bin": str(item.get("iin_bin") or ""),
            "name": str(item.get("name") or str(item.get("iin_bin") or "-")),
            "total_amount": float(item.get("total_amount") or 0.0),
        }
        for item in taxpayers
    ]

    requested_taxpayer = str(iin_bin or "").strip()
    selected_node = None
    if requested_taxpayer and requested_taxpayer in by_taxpayer:
        selected_node = by_taxpayer[requested_taxpayer]
    elif taxpayers:
        selected_node = taxpayers[0]

    available_months = sorted(
        {
            str(period_key or "").strip()
            for item in taxpayers
            for period_key in dict(item.get("monthly") or {}).keys()
            if re.match(r"^\d{4}-\d{2}$", str(period_key or "").strip())
        },
        reverse=True,
    )

    compare_target = str(compare_month or "").strip()
    if not compare_target:
        if (not is_all_periods) and re.match(r"^\d{4}-\d{2}$", period_norm):
            compare_target = period_norm
        elif available_months:
            compare_target = available_months[0]

    table_year = ""
    if re.match(r"^\d{4}-\d{2}$", compare_target):
        table_year = str(compare_target).split("-")[0]
    elif (not is_all_periods) and re.match(r"^\d{4}-\d{2}$", period_norm):
        table_year = str(period_norm).split("-")[0]
    elif available_months:
        table_year = str(available_months[0]).split("-")[0]

    month_keys = [f"{m:02d}" for m in range(1, 13)]
    comparison_monthly_rows: list[dict[str, Any]] = []
    comparison_quarterly_rows: list[dict[str, Any]] = []
    comparison_aggregated_rows: list[dict[str, Any]] = []
    for node in taxpayers:
        monthly_map = dict(node.get("monthly") or {})
        if table_year:
            month_values = {k: float(monthly_map.get(f"{table_year}-{k}", 0.0)) for k in month_keys}
        else:
            month_values = {k: 0.0 for k in month_keys}
        q1 = month_values["01"] + month_values["02"] + month_values["03"]
        q2 = month_values["04"] + month_values["05"] + month_values["06"]
        q3 = month_values["07"] + month_values["08"] + month_values["09"]
        q4 = month_values["10"] + month_values["11"] + month_values["12"]
        year_total = q1 + q2 + q3 + q4
        aggregated_total = year_total if table_year else float(node.get("total_amount") or 0.0)
        base = {
            "iin_bin": str(node.get("iin_bin") or ""),
            "name": str(node.get("name") or str(node.get("iin_bin") or "-")),
        }
        comparison_monthly_rows.append(
            {
                **base,
                **{f"m_{k}": float(v) for k, v in month_values.items()},
                "total": float(year_total),
            }
        )
        comparison_quarterly_rows.append(
            {
                **base,
                "q1": float(q1),
                "q2": float(q2),
                "q3": float(q3),
                "q4": float(q4),
                "total": float(year_total),
            }
        )
        comparison_aggregated_rows.append(
            {
                **base,
                "amount": float(aggregated_total),
                "total": float(aggregated_total),
            }
        )

    comparison_monthly_rows = sorted(comparison_monthly_rows, key=lambda x: float(x.get("total") or 0.0), reverse=True)[:20]
    comparison_quarterly_rows = sorted(comparison_quarterly_rows, key=lambda x: float(x.get("total") or 0.0), reverse=True)[:20]
    comparison_aggregated_rows = sorted(comparison_aggregated_rows, key=lambda x: float(x.get("total") or 0.0), reverse=True)[:20]

    monthly_rows: list[dict[str, Any]] = []
    quarterly_map: dict[str, float] = {}
    if selected_node is not None:
        for period_key, amount in sorted(dict(selected_node.get("monthly") or {}).items()):
            if not re.match(r"^\d{4}-\d{2}$", str(period_key or "").strip()):
                continue
            monthly_rows.append({"period": str(period_key), "amount": float(amount or 0.0)})
            quarter = _period_to_quarter(str(period_key))
            if quarter:
                quarterly_map[quarter] = float(quarterly_map.get(quarter, 0.0) + float(amount or 0.0))
    quarterly_rows = [{"period": q, "amount": float(v)} for q, v in sorted(quarterly_map.items())]

    compare_payload = None
    if selected_node is not None and compare_target and re.match(r"^\d{4}-\d{2}$", compare_target):
        month_map = dict(selected_node.get("monthly") or {})
        current_amount = float(month_map.get(compare_target, 0.0))
        prev_period = _period_prev_year(compare_target)
        prev_amount = float(month_map.get(prev_period, 0.0))
        diff_amount = current_amount - prev_amount
        diff_percent = ((diff_amount / prev_amount) * 100.0) if prev_amount > 0 else None
        compare_payload = {
            "period": compare_target,
            "current_amount": current_amount,
            "prev_period": prev_period,
            "prev_amount": prev_amount,
            "diff_amount": diff_amount,
            "diff_percent": diff_percent,
        }

    selected_rows: list[dict[str, Any]] = []
    if selected_node is not None:
        selected_iin = str(selected_node.get("iin_bin") or "").strip()
        for x in clean_rows:
            raw_iin = str(x.get("iin_bin") or "").strip()
            fallback = raw_iin or str(x.get("counterparty_iin_field") or "").strip()
            parsed_iin, _ = _split_iin_name(str(x.get("counterparty_iin_field") or ""), raw_iin)
            key = parsed_iin or fallback
            if key == selected_iin:
                selected_rows.append(x)

    month_axis: list[str] = []
    series_year_compare: list[dict[str, Any]] = []
    kbk_structure: list[dict[str, Any]] = []
    seasonality = None
    profile = None
    if selected_node is not None:
        selected_iin = str(selected_node.get("iin_bin") or "").strip()
        compare_year = ""
        if re.match(r"^\d{4}-\d{2}$", compare_target):
            compare_year = str(compare_target).split("-")[0]
        elif (not is_all_periods) and re.match(r"^\d{4}-\d{2}$", period_norm):
            compare_year = str(period_norm).split("-")[0]
        else:
            months_all = sorted(
                {str(k) for k in dict(selected_node.get("monthly") or {}).keys() if re.match(r"^\d{4}-\d{2}$", str(k))}
            )
            if months_all:
                compare_year = str(months_all[-1]).split("-")[0]

        prev_year = str(int(compare_year) - 1) if compare_year and compare_year.isdigit() else ""
        month_axis = [f"{m:02d}" for m in range(1, 13)]
        month_map = dict(selected_node.get("monthly") or {})
        for m in month_axis:
            p_cur = f"{compare_year}-{m}" if compare_year else ""
            p_prev = f"{prev_year}-{m}" if prev_year else ""
            cur_amount = float(month_map.get(p_cur, 0.0)) if p_cur else 0.0
            prev_amount = float(month_map.get(p_prev, 0.0)) if p_prev else 0.0
            series_year_compare.append({"month": m, "current_amount": cur_amount, "prev_amount": prev_amount})

        kbk_map: dict[str, float] = {}
        for x in selected_rows:
            key = str(x.get("kbk") or "").strip() or "-"
            kbk_map[key] = float(kbk_map.get(key, 0.0) + float(x.get("amount") or 0.0))
        kbk_total = float(sum(kbk_map.values()))
        kbk_structure = [
            {
                "kbk": k,
                "amount": float(v),
                "share_percent": ((float(v) / kbk_total) * 100.0) if kbk_total else 0.0,
            }
            for k, v in sorted(kbk_map.items(), key=lambda t: float(t[1]), reverse=True)[:10]
        ]

        rows_by_month = [float(x.get("amount") or 0.0) for x in monthly_rows]
        peak_amount = max(rows_by_month) if rows_by_month else 0.0
        min_amount = min(rows_by_month) if rows_by_month else 0.0
        peak_period = ""
        min_period = ""
        if rows_by_month:
            peak_idx = rows_by_month.index(peak_amount)
            min_idx = rows_by_month.index(min_amount)
            peak_period = str(monthly_rows[peak_idx].get("period") or "")
            min_period = str(monthly_rows[min_idx].get("period") or "")
        spread_percent = ((peak_amount - min_amount) / min_amount * 100.0) if min_amount > 0 else None
        last3 = rows_by_month[-3:] if len(rows_by_month) >= 3 else rows_by_month
        forecast_3m = (sum(last3) / len(last3) * 3.0) if last3 else 0.0
        seasonality = {
            "peak_period": peak_period,
            "peak_amount": float(peak_amount),
            "min_period": min_period,
            "min_amount": float(min_amount),
            "spread_percent": spread_percent,
            "forecast_3m": float(forecast_3m),
        }

        mean_val = (sum(rows_by_month) / len(rows_by_month)) if rows_by_month else 0.0
        if mean_val > 0 and len(rows_by_month) > 1:
            variance = sum((v - mean_val) ** 2 for v in rows_by_month) / len(rows_by_month)
            std_dev = variance ** 0.5
            cv = std_dev / mean_val
            stability_index = max(0.0, min(100.0, 100.0 - (cv * 100.0)))
        else:
            stability_index = 100.0 if rows_by_month else 0.0
        risk_level = "Стабильно"
        if compare_payload and compare_payload.get("diff_percent") is not None:
            diff_val = float(compare_payload.get("diff_percent") or 0.0)
            if diff_val < -20.0:
                risk_level = "Высокий"
            elif diff_val < 0.0:
                risk_level = "Умеренный"

        rank_period = compare_target if re.match(r"^\d{4}-\d{2}$", compare_target) else period_norm
        rank_base: dict[str, float] = {}
        oked_rank_base: dict[str, float] = {}
        dominant_oked = ""
        dominant_oked_amount = 0.0
        for x in selected_rows:
            oked_key = str(x.get("oked_proxy") or "").strip() or "Не определен (proxy)"
            amount = float(x.get("amount") or 0.0)
            if amount > dominant_oked_amount:
                dominant_oked = oked_key
                dominant_oked_amount = amount
        for x in clean_rows:
            row_period = str(x.get("period") or "").strip()
            if rank_period and row_period != rank_period:
                continue
            raw_iin = str(x.get("iin_bin") or "").strip()
            fallback = raw_iin or str(x.get("counterparty_iin_field") or "").strip()
            parsed_iin, _ = _split_iin_name(str(x.get("counterparty_iin_field") or ""), raw_iin)
            key = parsed_iin or fallback
            if not key:
                continue
            amount = float(x.get("amount") or 0.0)
            rank_base[key] = float(rank_base.get(key, 0.0) + amount)
            if dominant_oked and str(x.get("oked_proxy") or "").strip() == dominant_oked:
                oked_rank_base[key] = float(oked_rank_base.get(key, 0.0) + amount)
        rank_region = 0
        rank_oked = 0
        if rank_base:
            sorted_rank = sorted(rank_base.items(), key=lambda t: float(t[1]), reverse=True)
            for idx, (key, _) in enumerate(sorted_rank, start=1):
                if key == selected_iin:
                    rank_region = idx
                    break
        if oked_rank_base:
            sorted_oked_rank = sorted(oked_rank_base.items(), key=lambda t: float(t[1]), reverse=True)
            for idx, (key, _) in enumerate(sorted_oked_rank, start=1):
                if key == selected_iin:
                    rank_oked = idx
                    break

        year_amount = 0.0
        if compare_year:
            year_amount = float(sum(float(v) for k, v in month_map.items() if str(k).startswith(f"{compare_year}-")))
        avg_monthly = (year_amount / 12.0) if compare_year else 0.0
        cur_period_amount = float(compare_payload.get("current_amount") or 0.0) if compare_payload else 0.0
        prev_period_amount = float(compare_payload.get("prev_amount") or 0.0) if compare_payload else 0.0
        yoy_percent = compare_payload.get("diff_percent") if compare_payload else None
        profile = {
            "name": str(selected_node.get("name") or ""),
            "iin_bin": selected_iin,
            "segment": taxpayer_segment.get(selected_iin, MSB_UNKNOWN),
            "region": region_norm,
            "oked": dominant_oked,
            "rank_region": rank_region,
            "rank_region_total": len(rank_base),
            "rank_oked": rank_oked,
            "rank_oked_total": len(oked_rank_base),
            "current_period_amount": cur_period_amount,
            "prev_year_amount": prev_period_amount,
            "yoy_percent": yoy_percent,
            "annual_amount": year_amount,
            "avg_monthly": avg_monthly,
            "stability_index_percent": float(stability_index),
            "risk_level": risk_level,
            "kbk_diversification_count": len(kbk_map),
            "forecast_3m": float((seasonality or {}).get("forecast_3m") or 0.0),
            "year": compare_year,
            "prev_year": prev_year,
        }

    return {
        "filters": {
            "region": region_norm,
            "period": period_norm,
            "kbk": str(kbk or "").strip(),
            "bank": str(bank or "").strip(),
            "category": str(category or "").strip(),
            "msb": msb_exact or msb_group_filter,
            "oked": str(oked or "").strip(),
        },
        "taxpayers": taxpayer_list,
        "selected_taxpayer": (
            {
                "iin_bin": str(selected_node.get("iin_bin") or ""),
                "name": str(selected_node.get("name") or str(selected_node.get("iin_bin") or "-")),
                "total_amount": float(selected_node.get("total_amount") or 0.0),
            }
            if selected_node is not None else None
        ),
        "available_months": available_months,
        "series_monthly": monthly_rows,
        "series_quarterly": quarterly_rows,
        "compare_month": compare_payload,
        "series_year_compare": series_year_compare,
        "kbk_structure": kbk_structure,
        "seasonality": seasonality,
        "profile": profile,
        "comparison_table": {
            "year": table_year or None,
            "monthly_rows": comparison_monthly_rows,
            "quarterly_rows": comparison_quarterly_rows,
            "aggregated_rows": comparison_aggregated_rows,
        },
    }
