import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DatabaseService:
    def __init__(self) -> None:
        default_path = Path(__file__).resolve().parents[2] / "data" / "lingodoc.db"
        self.database_path = Path(os.getenv("DATABASE_PATH", str(default_path)))
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def init_db(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT,
                    plan TEXT NOT NULL DEFAULT 'free',
                    subscription_status TEXT NOT NULL DEFAULT 'inactive',
                    paddle_customer_id TEXT,
                    paddle_subscription_id TEXT,
                    paddle_price_id TEXT,
                    paddle_subscription_updated_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS files (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    total_pages INTEGER NOT NULL,
                    storage_provider TEXT NOT NULL DEFAULT 'local',
                    storage_key TEXT NOT NULL DEFAULT '',
                    storage_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS exports (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    output_type TEXT NOT NULL,
                    format TEXT NOT NULL,
                    storage_provider TEXT NOT NULL,
                    storage_key TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES translation_tasks(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS translation_tasks (
                    id TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    source_lang TEXT NOT NULL,
                    target_lang TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    processed_pages INTEGER NOT NULL DEFAULT 0,
                    total_pages INTEGER NOT NULL DEFAULT 0,
                    requested_pages INTEGER NOT NULL DEFAULT 0,
                    translated_pages INTEGER NOT NULL DEFAULT 0,
                    is_partial INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS translation_task_pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    page_number INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    is_billed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY (task_id) REFERENCES translation_tasks(id) ON DELETE CASCADE,
                    UNIQUE(task_id, page_number)
                );

                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL UNIQUE,
                    file_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    pages INTEGER NOT NULL,
                    usage_month TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES translation_tasks(id) ON DELETE CASCADE,
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS usage_page_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    page_number INTEGER NOT NULL,
                    usage_month TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES translation_tasks(id) ON DELETE CASCADE,
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE(task_id, page_number)
                );

                CREATE TABLE IF NOT EXISTS paddle_webhook_events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    processed_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_files_user_id ON files(user_id);
                CREATE INDEX IF NOT EXISTS idx_translation_tasks_user_id ON translation_tasks(user_id);
                CREATE INDEX IF NOT EXISTS idx_translation_tasks_file_id ON translation_tasks(file_id);
                CREATE INDEX IF NOT EXISTS idx_translation_task_pages_task_id ON translation_task_pages(task_id);
                CREATE INDEX IF NOT EXISTS idx_exports_task_id ON exports(task_id);
                CREATE INDEX IF NOT EXISTS idx_exports_user_id ON exports(user_id);
                CREATE INDEX IF NOT EXISTS idx_usage_events_user_month ON usage_events(user_id, usage_month);
                CREATE INDEX IF NOT EXISTS idx_usage_events_task_id ON usage_events(task_id);
                CREATE INDEX IF NOT EXISTS idx_usage_page_events_user_month ON usage_page_events(user_id, usage_month);
                CREATE INDEX IF NOT EXISTS idx_usage_page_events_task_id ON usage_page_events(task_id);
                """
            )
            self._ensure_column(connection, "users", "plan", "TEXT NOT NULL DEFAULT 'free'")
            self._ensure_column(connection, "users", "subscription_status", "TEXT NOT NULL DEFAULT 'inactive'")
            self._ensure_column(connection, "users", "paddle_customer_id", "TEXT")
            self._ensure_column(connection, "users", "paddle_subscription_id", "TEXT")
            self._ensure_column(connection, "users", "paddle_price_id", "TEXT")
            self._ensure_column(connection, "users", "paddle_subscription_updated_at", "TEXT")
            self._ensure_column(connection, "files", "storage_provider", "TEXT NOT NULL DEFAULT 'local'")
            self._ensure_column(connection, "files", "storage_key", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "translation_tasks", "requested_pages", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "translation_tasks", "translated_pages", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "translation_tasks", "is_partial", "INTEGER NOT NULL DEFAULT 0")

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")

    def upsert_user(self, user_id: str, email: Optional[str] = None) -> None:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users (id, email, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    email = COALESCE(excluded.email, users.email),
                    updated_at = excluded.updated_at
                """,
                (user_id, email, now, now),
            )

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def has_processed_paddle_event(self, event_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM paddle_webhook_events WHERE id = ?",
                (event_id,),
            ).fetchone()
        return bool(row)

    def record_paddle_event(self, event_id: str, event_type: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO paddle_webhook_events (id, event_type, processed_at)
                VALUES (?, ?, ?)
                """,
                (event_id, event_type, _utc_now()),
            )

    def update_user_subscription(
        self,
        *,
        user_id: str,
        plan: str,
        subscription_status: str,
        paddle_customer_id: Optional[str] = None,
        paddle_subscription_id: Optional[str] = None,
        paddle_price_id: Optional[str] = None,
    ) -> None:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users (
                    id, plan, subscription_status, paddle_customer_id,
                    paddle_subscription_id, paddle_price_id,
                    paddle_subscription_updated_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    plan = excluded.plan,
                    subscription_status = excluded.subscription_status,
                    paddle_customer_id = COALESCE(excluded.paddle_customer_id, users.paddle_customer_id),
                    paddle_subscription_id = COALESCE(excluded.paddle_subscription_id, users.paddle_subscription_id),
                    paddle_price_id = COALESCE(excluded.paddle_price_id, users.paddle_price_id),
                    paddle_subscription_updated_at = excluded.paddle_subscription_updated_at,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    plan,
                    subscription_status,
                    paddle_customer_id,
                    paddle_subscription_id,
                    paddle_price_id,
                    now,
                    now,
                    now,
                ),
            )

    def create_file(
        self,
        file_id: str,
        user_id: str,
        original_filename: str,
        file_size: int,
        total_pages: int,
        storage_provider: str,
        storage_key: str,
        storage_path: str,
    ) -> None:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO files (
                    id, user_id, original_filename, file_size, total_pages,
                    storage_provider, storage_key, storage_path, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    user_id,
                    original_filename,
                    file_size,
                    total_pages,
                    storage_provider,
                    storage_key,
                    storage_path,
                    now,
                ),
            )

    def get_file(self, file_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        return dict(row) if row else None

    def delete_file(self, file_id: str, user_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM files WHERE id = ? AND user_id = ?",
                (file_id, user_id),
            )
        return cursor.rowcount > 0

    def create_translation_task(
        self,
        task_id: str,
        file_id: str,
        user_id: str,
        source_lang: str,
        target_lang: str,
    ) -> None:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO translation_tasks (
                    id, file_id, user_id, source_lang, target_lang, status,
                    progress, processed_pages, total_pages, requested_pages,
                    translated_pages, is_partial, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'processing', 0, 0, 0, 0, 0, 0, ?, ?)
                """,
                (task_id, file_id, user_id, source_lang, target_lang, now, now),
            )

    def update_translation_task(
        self,
        task_id: str,
        *,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        processed_pages: Optional[int] = None,
        total_pages: Optional[int] = None,
        error: Optional[str] = None,
        requested_pages: Optional[int] = None,
        translated_pages: Optional[int] = None,
        is_partial: Optional[bool] = None,
    ) -> None:
        updates = ["updated_at = ?"]
        values: list[Any] = [_utc_now()]

        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if progress is not None:
            updates.append("progress = ?")
            values.append(progress)
        if processed_pages is not None:
            updates.append("processed_pages = ?")
            values.append(processed_pages)
        if total_pages is not None:
            updates.append("total_pages = ?")
            values.append(total_pages)
        if error is not None:
            updates.append("error = ?")
            values.append(error)
        if requested_pages is not None:
            updates.append("requested_pages = ?")
            values.append(requested_pages)
        if translated_pages is not None:
            updates.append("translated_pages = ?")
            values.append(translated_pages)
        if is_partial is not None:
            updates.append("is_partial = ?")
            values.append(1 if is_partial else 0)

        values.append(task_id)

        with self._connect() as connection:
            connection.execute(
                f"UPDATE translation_tasks SET {', '.join(updates)} WHERE id = ?",
                values,
            )

    def get_translation_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM translation_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return dict(row) if row else None

    def find_resumable_translation_task(
        self,
        *,
        file_id: str,
        user_id: str,
        source_lang: str,
        target_lang: str,
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM translation_tasks
                WHERE file_id = ?
                  AND user_id = ?
                  AND source_lang = ?
                  AND target_lang = ?
                  AND status IN ('queued', 'processing', 'recoverable')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (file_id, user_id, source_lang, target_lang),
            ).fetchone()
        return dict(row) if row else None

    def list_file_task_ids(self, file_id: str) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM translation_tasks WHERE file_id = ?",
                (file_id,),
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def get_current_usage_month(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def get_user_monthly_usage(self, user_id: str, usage_month: Optional[str] = None) -> int:
        month = usage_month or self.get_current_usage_month()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT (
                    COALESCE((SELECT SUM(pages) FROM usage_events WHERE user_id = ? AND usage_month = ?), 0) +
                    COALESCE((SELECT COUNT(*) FROM usage_page_events WHERE user_id = ? AND usage_month = ?), 0)
                ) AS used_pages
                """,
                (user_id, month, user_id, month),
            ).fetchone()

        return int(row["used_pages"] or 0) if row else 0

    def record_usage_event(
        self,
        *,
        task_id: str,
        file_id: str,
        user_id: str,
        plan: str,
        pages: int,
        usage_month: Optional[str] = None,
    ) -> None:
        if pages <= 0:
            return

        month = usage_month or self.get_current_usage_month()
        now = _utc_now()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO usage_events (
                    task_id, file_id, user_id, plan, pages, usage_month, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, file_id, user_id, plan, pages, month, now),
            )

    def create_task_pages(self, task_id: str, total_pages: int) -> None:
        if total_pages <= 0:
            return

        now = _utc_now()
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO translation_task_pages (
                    task_id, page_number, status, retry_count, is_billed, created_at, updated_at
                )
                VALUES (?, ?, 'pending', 0, 0, ?, ?)
                """,
                [(task_id, page_number + 1, now, now) for page_number in range(total_pages)],
            )

    def list_task_pages(self, task_id: str) -> list[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM translation_task_pages
                WHERE task_id = ?
                ORDER BY page_number ASC
                """,
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def reset_processing_task_pages(self, task_id: str) -> None:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE translation_task_pages
                SET status = 'pending', updated_at = ?, started_at = NULL
                WHERE task_id = ? AND status = 'processing'
                """,
                (now, task_id),
            )

    def update_task_page(
        self,
        task_id: str,
        page_number: int,
        *,
        status: Optional[str] = None,
        retry_count: Optional[int] = None,
        last_error: Optional[str] = None,
        is_billed: Optional[bool] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> None:
        updates = ["updated_at = ?"]
        values: list[Any] = [_utc_now()]

        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if retry_count is not None:
            updates.append("retry_count = ?")
            values.append(retry_count)
        if last_error is not None:
            updates.append("last_error = ?")
            values.append(last_error)
        if is_billed is not None:
            updates.append("is_billed = ?")
            values.append(1 if is_billed else 0)
        if started_at is not None:
            updates.append("started_at = ?")
            values.append(started_at)
        if completed_at is not None:
            updates.append("completed_at = ?")
            values.append(completed_at)

        values.extend([task_id, page_number])
        with self._connect() as connection:
            connection.execute(
                f"UPDATE translation_task_pages SET {', '.join(updates)} WHERE task_id = ? AND page_number = ?",
                values,
            )

    def get_task_page_counts(self, task_id: str) -> Dict[str, int]:
        counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM translation_task_pages
                WHERE task_id = ?
                GROUP BY status
                """,
                (task_id,),
            ).fetchall()
        for row in rows:
            status = str(row["status"])
            counts[status] = int(row["count"])
        return counts

    def record_page_usage_event(
        self,
        *,
        task_id: str,
        file_id: str,
        user_id: str,
        plan: str,
        page_number: int,
        usage_month: Optional[str] = None,
    ) -> bool:
        month = usage_month or self.get_current_usage_month()
        now = _utc_now()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO usage_page_events (
                    task_id, file_id, user_id, plan, page_number, usage_month, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, file_id, user_id, plan, page_number, month, now),
            )
        return cursor.rowcount > 0

    def list_user_files(self, user_id: str) -> list[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    files.id,
                    files.original_filename,
                    files.file_size,
                    files.total_pages,
                    files.storage_provider,
                    files.storage_key,
                    files.created_at,
                    latest_task.id AS task_id,
                    latest_task.source_lang,
                    latest_task.target_lang,
                    latest_task.status,
                    latest_task.progress,
                    latest_task.processed_pages,
                    latest_task.total_pages AS task_total_pages,
                    latest_task.requested_pages,
                    latest_task.translated_pages,
                    latest_task.is_partial,
                    latest_task.error,
                    latest_task.created_at AS task_created_at,
                    latest_task.updated_at AS task_updated_at
                FROM files
                LEFT JOIN translation_tasks AS latest_task
                    ON latest_task.id = (
                        SELECT id
                        FROM translation_tasks
                        WHERE translation_tasks.file_id = files.id
                        ORDER BY created_at DESC
                        LIMIT 1
                    )
                WHERE files.user_id = ?
                ORDER BY files.created_at DESC
                """,
                (user_id,),
            ).fetchall()

        return [dict(row) for row in rows]


db_service = DatabaseService()
