import os
from pathlib import Path
from typing import Protocol


class StorageService(Protocol):
    provider: str

    def save_bytes(self, storage_key: str, content: bytes) -> None:
        ...

    def read_bytes(self, storage_key: str) -> bytes:
        ...

    def exists(self, storage_key: str) -> bool:
        ...

    def get_local_path(self, storage_key: str) -> str:
        ...


class LocalStorageService:
    provider = "local"

    def __init__(self) -> None:
        default_root = Path(__file__).resolve().parents[2]
        self.root_dir = Path(os.getenv("LOCAL_STORAGE_ROOT", str(default_root))).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_key(self, storage_key: str) -> Path:
        clean_key = storage_key.replace("\\", "/").lstrip("/")
        target_path = (self.root_dir / clean_key).resolve()

        if self.root_dir not in target_path.parents and target_path != self.root_dir:
            raise ValueError("Invalid storage key")

        return target_path

    def save_bytes(self, storage_key: str, content: bytes) -> None:
        target_path = self._resolve_key(storage_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)

    def read_bytes(self, storage_key: str) -> bytes:
        return self._resolve_key(storage_key).read_bytes()

    def exists(self, storage_key: str) -> bool:
        return self._resolve_key(storage_key).exists()

    def get_local_path(self, storage_key: str) -> str:
        return str(self._resolve_key(storage_key))


storage_service: StorageService = LocalStorageService()
