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

    def delete(self, storage_key: str) -> None:
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

    def delete(self, storage_key: str) -> None:
        target_path = self._resolve_key(storage_key)
        if target_path.exists():
            target_path.unlink()

    def get_local_path(self, storage_key: str) -> str:
        return str(self._resolve_key(storage_key))


class R2StorageService:
    provider = "r2"

    def __init__(self) -> None:
        self.bucket = os.getenv("R2_BUCKET", "").strip()
        self.endpoint_url = os.getenv("R2_ENDPOINT_URL", "").strip()
        self.access_key_id = os.getenv("R2_ACCESS_KEY_ID", "").strip()
        self.secret_access_key = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()

        missing = [
            name
            for name, value in {
                "R2_BUCKET": self.bucket,
                "R2_ENDPOINT_URL": self.endpoint_url,
                "R2_ACCESS_KEY_ID": self.access_key_id,
                "R2_SECRET_ACCESS_KEY": self.secret_access_key,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing R2 configuration: {', '.join(missing)}")

        default_cache_dir = Path(__file__).resolve().parents[2] / "tmp" / "storage-cache"
        self.cache_dir = Path(os.getenv("LOCAL_STORAGE_CACHE_DIR", str(default_cache_dir))).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = self._create_client()

    def _create_client(self):
        import boto3

        return boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name="auto",
        )

    def _normalize_key(self, storage_key: str) -> str:
        clean_key = storage_key.replace("\\", "/").lstrip("/")
        if not clean_key or ".." in clean_key.split("/"):
            raise ValueError("Invalid storage key")
        return clean_key

    def _cache_path(self, storage_key: str) -> Path:
        clean_key = self._normalize_key(storage_key)
        target_path = (self.cache_dir / clean_key).resolve()

        if self.cache_dir not in target_path.parents and target_path != self.cache_dir:
            raise ValueError("Invalid storage key")

        return target_path

    def _write_cache(self, storage_key: str, content: bytes) -> None:
        target_path = self._cache_path(storage_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)

    def save_bytes(self, storage_key: str, content: bytes) -> None:
        clean_key = self._normalize_key(storage_key)
        self.client.put_object(Bucket=self.bucket, Key=clean_key, Body=content)
        self._write_cache(clean_key, content)

    def read_bytes(self, storage_key: str) -> bytes:
        clean_key = self._normalize_key(storage_key)
        response = self.client.get_object(Bucket=self.bucket, Key=clean_key)
        content = response["Body"].read()
        self._write_cache(clean_key, content)
        return content

    def exists(self, storage_key: str) -> bool:
        clean_key = self._normalize_key(storage_key)
        try:
            self.client.head_object(Bucket=self.bucket, Key=clean_key)
            return True
        except Exception:
            return False

    def delete(self, storage_key: str) -> None:
        clean_key = self._normalize_key(storage_key)
        self.client.delete_object(Bucket=self.bucket, Key=clean_key)
        cache_path = self._cache_path(clean_key)
        if cache_path.exists():
            cache_path.unlink()

    def get_local_path(self, storage_key: str) -> str:
        clean_key = self._normalize_key(storage_key)
        target_path = self._cache_path(clean_key)
        if not target_path.exists():
            self.read_bytes(clean_key)
        return str(target_path)


def create_storage_service() -> StorageService:
    provider = os.getenv("STORAGE_PROVIDER", "local").strip().lower()
    if provider == "local":
        return LocalStorageService()
    if provider == "r2":
        return R2StorageService()
    raise RuntimeError(f"Unsupported STORAGE_PROVIDER: {provider}")


storage_service: StorageService = create_storage_service()
