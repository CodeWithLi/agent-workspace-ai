import logging
from io import BytesIO
from pathlib import Path

from app.core.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()


class ObjectStorageError(RuntimeError):
    pass


class ObjectStorage:
    def _client(self):
        from minio import Minio

        client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        if not client.bucket_exists(settings.minio_bucket):
            client.make_bucket(settings.minio_bucket)
        return client

    def save(self, object_name: str, data: bytes, content_type: str) -> str:
        try:
            self._client().put_object(
                settings.minio_bucket,
                object_name,
                BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            return f"minio://{settings.minio_bucket}/{object_name}"
        except Exception as exc:
            if not settings.storage_fallback_enabled:
                raise ObjectStorageError("MinIO upload failed") from exc
            logger.warning("MinIO unavailable; saving upload locally: %s", exc)
            target = Path(settings.local_upload_dir) / object_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            return str(target)

    def delete(self, storage_path: str) -> None:
        if storage_path.startswith("minio://"):
            path = storage_path.removeprefix("minio://")
            bucket, object_name = path.split("/", 1)
            try:
                self._client().remove_object(bucket, object_name)
            except Exception as exc:
                raise ObjectStorageError("MinIO delete failed") from exc
            return
        path = Path(storage_path)
        if path.exists() and path.is_file():
            path.unlink()


object_storage = ObjectStorage()
