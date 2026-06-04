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
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_files_user_id ON files(user_id);
                CREATE INDEX IF NOT EXISTS idx_translation_tasks_user_id ON translation_tasks(user_id);
                CREATE INDEX IF NOT EXISTS idx_translation_tasks_file_id ON translation_tasks(file_id);
                CREATE INDEX IF NOT EXISTS idx_exports_task_id ON exports(task_id);
                CREATE INDEX IF NOT EXISTS idx_exports_user_id ON exports(user_id);
                """
            )
            self._ensure_column(connection, "files", "storage_provider", "TEXT NOT NULL DEFAULT 'local'")
            self._ensure_column(connection, "files", "storage_key", "TEXT NOT NULL DEFAULT ''")

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
                    progress, processed_pages, total_pages, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'processing', 0, 0, 0, ?, ?)
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
