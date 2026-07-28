from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import StoredObject, utcnow

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class StorageError(RuntimeError):
    pass


class StorageObjectMissing(StorageError):
    pass


@dataclass(frozen=True)
class StorageLocator:
    backend: str
    bucket: str
    object_key: str


@dataclass(frozen=True)
class StoredObjectStat:
    size_bytes: int
    sha256: str | None
    content_type: str | None


class StorageBackend(Protocol):
    name: str
    bucket: str

    def put_bytes(
        self,
        object_key: str,
        data: bytes,
        *,
        content_type: str,
        sha256: str,
    ) -> StoredObjectStat: ...

    def read_bytes(self, object_key: str) -> bytes: ...

    def stat(self, object_key: str) -> StoredObjectStat: ...

    def delete(self, object_key: str) -> None: ...

    def exists(self, object_key: str) -> bool: ...

    def local_path(self, object_key: str) -> Path | None: ...

    def presigned_get(self, object_key: str, *, expires_seconds: int) -> str | None: ...

    def check_ready(self) -> None: ...


def _validated_key(object_key: str) -> str:
    if not object_key or "\\" in object_key or object_key.startswith("/"):
        raise StorageError("Invalid storage object key")
    parts = PurePosixPath(object_key).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise StorageError("Invalid storage object key")
    if any(not _SAFE_SEGMENT.fullmatch(part) for part in parts):
        raise StorageError("Invalid storage object key segment")
    return "/".join(parts)


def _segment(value: str) -> str:
    if not _SAFE_SEGMENT.fullmatch(value):
        raise StorageError("Invalid storage key identifier")
    return value


def _tenant_key(
    object_key: str,
    *,
    organization_id: str,
    project_id: str | None,
) -> str:
    key = _validated_key(object_key)
    prefix = f"org/{_segment(organization_id)}/"
    if not key.startswith(prefix):
        raise StorageError("Storage object key does not match its organization")
    if project_id is not None:
        project_prefix = f"{prefix}project/{_segment(project_id)}/"
        if not key.startswith(project_prefix):
            raise StorageError("Storage object key does not match its project")
    return key


def _suffix(filename: str | None, content_type: str | None = None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix and re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
        return suffix
    guessed = mimetypes.guess_extension(content_type or "") or ""
    return guessed if re.fullmatch(r"\.[a-z0-9]{1,10}", guessed) else ""


def document_object_key(
    organization_id: str,
    project_id: str,
    document_id: str,
    *,
    filename: str,
    content_type: str,
) -> str:
    return _validated_key(
        f"org/{_segment(organization_id)}/project/{_segment(project_id)}/"
        f"documents/{_segment(document_id)}/source"
        f"{_suffix(filename, content_type)}"
    )


def evidence_object_key(
    organization_id: str,
    project_id: str,
    asset_id: str,
    *,
    kind: str,
    page_number: int,
    sequence: int,
    filename: str | None,
    content_type: str | None,
) -> str:
    safe_kind = re.sub(r"[^a-z0-9_-]", "-", kind.lower())[:40] or "asset"
    return _validated_key(
        f"org/{_segment(organization_id)}/project/{_segment(project_id)}/"
        f"evidence/{_segment(asset_id)}/"
        f"{safe_kind}-{max(0, page_number):04d}-{max(0, sequence):03d}"
        f"{_suffix(filename, content_type)}"
    )


def export_object_key(
    organization_id: str,
    artifact_id: str,
    *,
    content_type: str = "application/json",
) -> str:
    return _validated_key(
        f"org/{_segment(organization_id)}/exports/"
        f"{_segment(artifact_id)}{_suffix(None, content_type) or '.json'}"
    )


class LocalStorageBackend:
    name = "local"
    bucket = ""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, object_key: str) -> Path:
        key = _validated_key(object_key)
        path = (self.root / Path(*PurePosixPath(key).parts)).resolve()
        if self.root != path and self.root not in path.parents:
            raise StorageError("Storage key escapes local root")
        return path

    def put_bytes(
        self,
        object_key: str,
        data: bytes,
        *,
        content_type: str,
        sha256: str,
    ) -> StoredObjectStat:
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if actual_sha256 != sha256:
            raise StorageError("Storage checksum mismatch before write")
        target = self._path(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            dir=target.parent,
            prefix=".tmp-",
            delete=False,
        )
        temporary = Path(handle.name)
        try:
            with handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return StoredObjectStat(
            size_bytes=len(data),
            sha256=actual_sha256,
            content_type=content_type,
        )

    def read_bytes(self, object_key: str) -> bytes:
        try:
            return self._path(object_key).read_bytes()
        except FileNotFoundError as exc:
            raise StorageObjectMissing(object_key) from exc

    def stat(self, object_key: str) -> StoredObjectStat:
        path = self._path(object_key)
        if not path.is_file():
            raise StorageObjectMissing(object_key)
        data = path.read_bytes()
        return StoredObjectStat(
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            content_type=mimetypes.guess_type(path.name)[0],
        )

    def delete(self, object_key: str) -> None:
        path = self._path(object_key)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        parent = path.parent
        while parent != self.root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def exists(self, object_key: str) -> bool:
        return self._path(object_key).is_file()

    def local_path(self, object_key: str) -> Path | None:
        path = self._path(object_key)
        return path if path.is_file() else None

    def presigned_get(self, object_key: str, *, expires_seconds: int) -> str | None:
        _validated_key(object_key)
        return None

    def check_ready(self) -> None:
        if not self.root.is_dir() or not os.access(self.root, os.R_OK | os.W_OK):
            raise StorageError("Local storage root is unavailable")


class S3StorageBackend:
    name = "s3"

    def __init__(self, settings: Settings, *, client=None):
        if not settings.s3_bucket:
            raise StorageError("S3 bucket is not configured")
        self.bucket = settings.s3_bucket
        self.settings = settings
        if client is None:
            import boto3

            kwargs = {
                "service_name": "s3",
                "region_name": settings.s3_region,
                "endpoint_url": settings.s3_endpoint_url,
                "use_ssl": settings.s3_require_tls,
            }
            if settings.s3_access_key_id:
                kwargs["aws_access_key_id"] = (
                    settings.s3_access_key_id.get_secret_value()
                )
            if settings.s3_secret_access_key:
                kwargs["aws_secret_access_key"] = (
                    settings.s3_secret_access_key.get_secret_value()
                )
            client = boto3.client(**kwargs)
        self.client = client

    def put_bytes(
        self,
        object_key: str,
        data: bytes,
        *,
        content_type: str,
        sha256: str,
    ) -> StoredObjectStat:
        key = _validated_key(object_key)
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if actual_sha256 != sha256:
            raise StorageError("Storage checksum mismatch before write")
        kwargs = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": data,
            "ContentType": content_type,
            "Metadata": {"sha256": actual_sha256},
        }
        if self.settings.s3_server_side_encryption != "none":
            kwargs["ServerSideEncryption"] = (
                self.settings.s3_server_side_encryption
            )
        if self.settings.s3_kms_key_id:
            kwargs["SSEKMSKeyId"] = self.settings.s3_kms_key_id
        try:
            self.client.put_object(**kwargs)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError("S3 write failed") from exc
        result = self.stat(key)
        if result.size_bytes != len(data) or result.sha256 != actual_sha256:
            raise StorageError("S3 verification failed after write")
        return result

    def read_bytes(self, object_key: str) -> bytes:
        key = _validated_key(object_key)
        try:
            body: BinaryIO = self.client.get_object(
                Bucket=self.bucket,
                Key=key,
            )["Body"]
            return body.read()
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise StorageObjectMissing(key) from exc
            raise StorageError("S3 read failed") from exc
        except BotoCoreError as exc:
            raise StorageError("S3 read failed") from exc

    def stat(self, object_key: str) -> StoredObjectStat:
        key = _validated_key(object_key)
        try:
            result = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise StorageObjectMissing(key) from exc
            raise StorageError("S3 stat failed") from exc
        except BotoCoreError as exc:
            raise StorageError("S3 stat failed") from exc
        return StoredObjectStat(
            size_bytes=int(result["ContentLength"]),
            sha256=(result.get("Metadata") or {}).get("sha256"),
            content_type=result.get("ContentType"),
        )

    def delete(self, object_key: str) -> None:
        try:
            self.client.delete_object(
                Bucket=self.bucket,
                Key=_validated_key(object_key),
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError("S3 delete failed") from exc

    def exists(self, object_key: str) -> bool:
        try:
            self.stat(object_key)
        except StorageObjectMissing:
            return False
        return True

    def local_path(self, object_key: str) -> Path | None:
        _validated_key(object_key)
        return None

    def presigned_get(self, object_key: str, *, expires_seconds: int) -> str | None:
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": _validated_key(object_key)},
                ExpiresIn=expires_seconds,
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError("S3 presigning failed") from exc

    def check_ready(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError("S3 bucket is unavailable") from exc


def build_storage_backend(settings: Settings, *, s3_client=None) -> StorageBackend:
    issues = settings.storage_configuration_issues()
    if issues:
        raise StorageError("Unsafe storage configuration: " + ", ".join(issues))
    if settings.storage_backend == "s3":
        return S3StorageBackend(settings, client=s3_client)
    return LocalStorageBackend(settings.storage_local_root)


class StorageService:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        *,
        backend: StorageBackend | None = None,
    ):
        self.db = db
        self.settings = settings
        self.backend = backend or build_storage_backend(settings)

    def store_bytes(
        self,
        *,
        organization_id: str,
        project_id: str | None,
        resource_type: str,
        resource_id: str,
        purpose: str,
        object_key: str,
        data: bytes,
        content_type: str,
    ) -> StoredObject:
        key = _tenant_key(
            object_key,
            organization_id=organization_id,
            project_id=project_id,
        )
        sha256 = hashlib.sha256(data).hexdigest()
        stat = self.backend.put_bytes(
            key,
            data,
            content_type=content_type,
            sha256=sha256,
        )
        stored = StoredObject(
            organization_id=organization_id,
            project_id=project_id,
            resource_type=resource_type,
            resource_id=resource_id,
            purpose=purpose,
            backend=self.backend.name,
            bucket=self.backend.bucket,
            object_key=key,
            content_type=content_type,
            size_bytes=stat.size_bytes,
            sha256=sha256,
            status="active",
        )
        self.db.add(stored)
        self.db.flush()
        return stored

    def backend_for(self, stored: StoredObject) -> StorageBackend:
        _tenant_key(
            stored.object_key,
            organization_id=stored.organization_id,
            project_id=stored.project_id,
        )
        if (
            stored.backend == self.backend.name
            and stored.bucket == self.backend.bucket
        ):
            return self.backend
        raise StorageError(
            f"Storage backend is unavailable: {stored.backend}:{stored.bucket}"
        )

    def read_bytes(self, stored: StoredObject) -> bytes:
        data = self.backend_for(stored).read_bytes(stored.object_key)
        if hashlib.sha256(data).hexdigest() != stored.sha256:
            raise StorageError("Stored object checksum verification failed")
        return data

    def verify(self, stored: StoredObject) -> StoredObjectStat:
        stat = self.backend_for(stored).stat(stored.object_key)
        if stat.size_bytes != stored.size_bytes:
            raise StorageError("Stored object size verification failed")
        if stat.sha256 and stat.sha256 != stored.sha256:
            raise StorageError("Stored object checksum metadata mismatch")
        return stat

    def delete(self, stored: StoredObject) -> None:
        self.backend_for(stored).delete(stored.object_key)
        stored.status = "deleted"
        stored.deleted_at = utcnow()
        self.db.flush()

    @contextmanager
    def materialize(self, stored: StoredObject) -> Iterator[Path]:
        backend = self.backend_for(stored)
        local = backend.local_path(stored.object_key)
        if local is not None:
            yield local
            return
        suffix = _suffix(stored.object_key, stored.content_type)
        handle = tempfile.NamedTemporaryFile(
            prefix="ai-examiner-object-",
            suffix=suffix,
            delete=False,
        )
        temporary = Path(handle.name)
        try:
            with handle:
                handle.write(self.read_bytes(stored))
            yield temporary
        finally:
            temporary.unlink(missing_ok=True)

    def presigned_get(self, stored: StoredObject) -> str | None:
        return self.backend_for(stored).presigned_get(
            stored.object_key,
            expires_seconds=self.settings.s3_presign_ttl_seconds,
        )


@contextmanager
def materialize_resource(
    db: Session,
    settings: Settings,
    *,
    organization_id: str,
    storage_object_id: str | None,
    legacy_path: str | None,
) -> Iterator[Path]:
    if storage_object_id:
        stored = db.get(StoredObject, storage_object_id)
        if (
            stored is None
            or stored.organization_id != organization_id
            or stored.status != "active"
        ):
            raise StorageObjectMissing(storage_object_id)
        with StorageService(db, settings).materialize(stored) as path:
            yield path
        return
    if not legacy_path:
        raise StorageObjectMissing("unlocated")
    path = Path(legacy_path).resolve()
    if not path.is_file():
        raise StorageObjectMissing(legacy_path)
    yield path
