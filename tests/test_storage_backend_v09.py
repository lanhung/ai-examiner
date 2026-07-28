from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from botocore.exceptions import ClientError
from sqlalchemy import create_engine, inspect, select, text

from ai_examiner.config import Settings
from ai_examiner.db import Base, SessionLocal
from ai_examiner.enterprise_constants import (
    LEGACY_ORGANIZATION_ID,
    LOCAL_IDENTITY_ISSUER,
)
from ai_examiner.models import (
    Document,
    EvidenceAsset,
    LearnerIdentity,
    MemoryExportArtifact,
    Organization,
    Project,
    StoredObject,
    utcnow,
)
from ai_examiner.services.enterprise_identity import bootstrap_owner
from ai_examiner.services.storage import (
    LocalStorageBackend,
    S3StorageBackend,
    StorageError,
    StorageObjectMissing,
    StorageService,
    document_object_key,
    evidence_object_key,
    export_object_key,
)
from ai_examiner.services.storage_migration import (
    migrate_legacy_storage,
    reconcile_storage,
)


class FakeS3Client:
    def __init__(self):
        self.objects: dict[tuple[str, str], dict] = {}
        self.last_put: dict | None = None

    @staticmethod
    def _missing(operation: str) -> ClientError:
        return ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
            operation,
        )

    def put_object(self, **kwargs):
        self.last_put = kwargs
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = {
            "Body": bytes(kwargs["Body"]),
            "ContentType": kwargs["ContentType"],
            "Metadata": dict(kwargs["Metadata"]),
        }
        return {"ETag": '"fake"'}

    def head_object(self, *, Bucket: str, Key: str):
        try:
            item = self.objects[(Bucket, Key)]
        except KeyError as exc:
            raise self._missing("HeadObject") from exc
        return {
            "ContentLength": len(item["Body"]),
            "ContentType": item["ContentType"],
            "Metadata": item["Metadata"],
        }

    def get_object(self, *, Bucket: str, Key: str):
        try:
            item = self.objects[(Bucket, Key)]
        except KeyError as exc:
            raise self._missing("GetObject") from exc
        return {"Body": io.BytesIO(item["Body"])}

    def delete_object(self, *, Bucket: str, Key: str):
        self.objects.pop((Bucket, Key), None)
        return {}

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        assert operation == "get_object"
        return (
            f"https://objects.example/{Params['Bucket']}/{Params['Key']}"
            f"?expires={ExpiresIn}"
        )

    def head_bucket(self, *, Bucket: str):
        assert Bucket
        return {}


def _exercise_backend(backend) -> None:
    key = "org/tenant/project/project/documents/document/source.txt"
    data = b"tenant object"
    checksum = hashlib.sha256(data).hexdigest()

    written = backend.put_bytes(
        key,
        data,
        content_type="text/plain",
        sha256=checksum,
    )
    assert written.size_bytes == len(data)
    assert written.sha256 == checksum
    assert backend.exists(key)
    assert backend.read_bytes(key) == data
    assert backend.stat(key).size_bytes == len(data)
    backend.check_ready()
    rewritten = backend.put_bytes(
        key,
        data,
        content_type="text/plain",
        sha256=checksum,
    )
    assert rewritten.sha256 == checksum

    backend.delete(key)
    assert not backend.exists(key)
    with pytest.raises(StorageObjectMissing):
        backend.read_bytes(key)


def test_local_and_s3_backends_share_the_same_contract(tmp_path):
    local = LocalStorageBackend(tmp_path / "objects")
    _exercise_backend(local)
    assert local.presigned_get("org/tenant/file.txt", expires_seconds=60) is None

    client = FakeS3Client()
    settings = Settings(
        storage_backend="s3",
        s3_bucket="examiner-private",
        s3_endpoint_url="https://minio.example.test",
        s3_server_side_encryption="AES256",
    )
    s3 = S3StorageBackend(settings, client=client)
    _exercise_backend(s3)
    assert client.last_put["ServerSideEncryption"] == "AES256"
    assert s3.presigned_get(
        "org/tenant/file.txt",
        expires_seconds=60,
    ).startswith("https://objects.example/examiner-private/")


def test_storage_keys_are_tenant_scoped_and_reject_unsafe_identifiers():
    assert document_object_key(
        "org-a",
        "project-a",
        "document-a",
        filename="paper.PDF",
        content_type="application/pdf",
    ) == "org/org-a/project/project-a/documents/document-a/source.pdf"
    assert evidence_object_key(
        "org-a",
        "project-a",
        "asset-a",
        kind="Page Preview",
        page_number=2,
        sequence=1,
        filename="page.png",
        content_type="image/png",
    ).startswith("org/org-a/project/project-a/evidence/asset-a/")
    assert export_object_key("org-a", "export-a") == (
        "org/org-a/exports/export-a.json"
    )

    with pytest.raises(StorageError):
        document_object_key(
            "../org-a",
            "project-a",
            "document-a",
            filename="paper.pdf",
            content_type="application/pdf",
        )
    with pytest.raises(StorageError):
        LocalStorageBackend(Path.cwd()).read_bytes("../secret")


def test_s3_configuration_requires_tls_and_complete_kms_configuration():
    insecure = Settings(
        storage_backend="s3",
        s3_bucket="private",
        s3_endpoint_url="http://minio.example.test",
        s3_require_tls=True,
    )
    assert "s3_endpoint_requires_https" in insecure.storage_configuration_issues()

    explicit_http = Settings(
        storage_backend="s3",
        s3_bucket="private",
        s3_endpoint_url="http://minio:9000",
        s3_require_tls=False,
    )
    assert "s3_insecure_http_not_allowed" in (
        explicit_http.storage_configuration_issues()
    )
    explicitly_allowed = Settings(
        storage_backend="s3",
        s3_bucket="private",
        s3_endpoint_url="http://minio:9000",
        s3_require_tls=False,
        s3_allow_insecure_http=True,
        s3_server_side_encryption="none",
    )
    assert explicitly_allowed.storage_configuration_issues() == []

    kms = Settings(
        storage_backend="s3",
        s3_bucket="private",
        s3_server_side_encryption="aws:kms",
    )
    assert "missing_s3_kms_key_id" in kms.storage_configuration_issues()


def test_storage_service_records_locator_and_verifies_checksum(tmp_path):
    settings = Settings(
        storage_backend="local",
        storage_local_root=tmp_path / "objects",
    )
    with SessionLocal() as db:
        project = Project(name="Storage service", domain="test", language="en")
        db.add(project)
        db.flush()
        stored = StorageService(db, settings).store_bytes(
            organization_id=project.organization_id,
            project_id=project.id,
            resource_type="document",
            resource_id="document-id",
            purpose="source",
            object_key=document_object_key(
                project.organization_id,
                project.id,
                "document-id",
                filename="paper.txt",
                content_type="text/plain",
            ),
            data=b"grounded",
            content_type="text/plain",
        )
        db.commit()

        assert stored.object_key.startswith(
            f"org/{LEGACY_ORGANIZATION_ID}/project/{project.id}/"
        )
        assert StorageService(db, settings).read_bytes(stored) == b"grounded"
        path = settings.storage_local_root / Path(*stored.object_key.split("/"))
        path.write_bytes(b"tampered")
        with pytest.raises(StorageError, match="checksum"):
            StorageService(db, settings).read_bytes(stored)
        with pytest.raises(StorageError, match="organization"):
            StorageService(db, settings).store_bytes(
                organization_id=project.organization_id,
                project_id=project.id,
                resource_type="document",
                resource_id="foreign-document",
                purpose="source",
                object_key=(
                    "org/foreign/project/"
                    f"{project.id}/documents/foreign-document/source.txt"
                ),
                data=b"foreign",
                content_type="text/plain",
            )


def test_upload_uses_locator_and_authorized_download(client):
    with SessionLocal() as db:
        _, principal, _ = bootstrap_owner(
            db,
            issuer=LOCAL_IDENTITY_ISSUER,
            subject="storage-download-owner",
        )
        db.commit()
        principal_id = principal.id
    project = client.post("/api/projects", json={"name": "Stored upload"}).json()
    raw = b"Storage-backed research evidence"
    uploaded = client.post(
        f"/api/projects/{project['id']}/documents",
        files={"file": ("paper.txt", raw, "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text

    with SessionLocal() as db:
        document = db.get(Document, uploaded.json()["id"])
        assert document.storage_path is None
        assert document.storage_object_id
        stored = db.get(StoredObject, document.storage_object_id)
        assert stored.object_key.startswith(
            f"org/{LEGACY_ORGANIZATION_ID}/project/{project['id']}/documents/"
        )

    downloaded = client.get(
        f"/api/v1/documents/{uploaded.json()['id']}/file",
        headers={
            "X-AI-Examiner-Organization": LEGACY_ORGANIZATION_ID,
            "X-AI-Examiner-Principal": principal_id,
        },
    )
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == raw
    assert "no-store" in downloaded.headers["cache-control"]


def test_authorized_download_rejects_cross_tenant_resource(client, tmp_path):
    source = tmp_path / "foreign.txt"
    source.write_bytes(b"foreign tenant")
    with SessionLocal() as db:
        organization_a = Organization(
            slug="storage-a",
            display_name="Storage A",
            status="active",
        )
        organization_b = Organization(
            slug="storage-b",
            display_name="Storage B",
            status="active",
        )
        db.add_all([organization_a, organization_b])
        db.flush()
        _, principal, _ = bootstrap_owner(
            db,
            issuer=LOCAL_IDENTITY_ISSUER,
            subject="storage-a-owner",
            organization_id=organization_a.id,
        )
        project_b = Project(
            organization_id=organization_b.id,
            name="Foreign storage",
            domain="test",
            language="en",
        )
        db.add(project_b)
        db.flush()
        document_b = Document(
            organization_id=organization_b.id,
            project_id=project_b.id,
            filename="foreign.txt",
            content_type="text/plain",
            storage_path=str(source),
            content_text="foreign",
            page_map=[],
            parse_warnings=[],
            char_count=7,
        )
        db.add(document_b)
        db.commit()
        principal_id = principal.id
        organization_a_id = organization_a.id
        document_b_id = document_b.id

    denied = client.get(
        f"/api/v1/documents/{document_b_id}/file",
        headers={
            "X-AI-Examiner-Organization": organization_a_id,
            "X-AI-Examiner-Principal": principal_id,
        },
    )
    assert denied.status_code == 404
    assert b"foreign tenant" not in denied.content


def test_legacy_migration_resumes_without_duplicate_objects(tmp_path):
    sources = tmp_path / "legacy"
    sources.mkdir()
    document_path = sources / "paper.txt"
    evidence_path = sources / "page.png"
    export_path = sources / "memory.json"
    document_path.write_bytes(b"legacy document")
    evidence_path.write_bytes(b"legacy evidence")
    export_path.write_text('{"memory": true}', encoding="utf-8")

    with SessionLocal() as db:
        project = Project(name="Legacy migration", domain="test", language="en")
        identity = LearnerIdentity(
            opaque_key_hash="a" * 64,
            display_name="Migration learner",
        )
        db.add_all([project, identity])
        db.flush()
        document = Document(
            project_id=project.id,
            filename="paper.txt",
            content_type="text/plain",
            storage_path=str(document_path),
            content_text="legacy document",
            page_map=[],
            parse_warnings=[],
            char_count=15,
        )
        db.add(document)
        db.flush()
        db.add_all(
            [
                EvidenceAsset(
                    project_id=project.id,
                    document_id=document.id,
                    kind="page",
                    page_number=1,
                    sequence=0,
                    label="Page 1",
                    storage_path=str(evidence_path),
                    mime_type="image/png",
                ),
                MemoryExportArtifact(
                    learner_identity_id=identity.id,
                    storage_path=str(export_path),
                    scope_json={},
                    record_counts={},
                    expires_at=utcnow() + timedelta(hours=1),
                ),
            ]
        )
        db.commit()

        settings = Settings(
            storage_backend="local",
            storage_local_root=tmp_path / "objects",
        )
        checkpoint = tmp_path / "migration-checkpoint.json"
        first = migrate_legacy_storage(
            db,
            settings,
            checkpoint_path=checkpoint,
            limit=1,
        )
        assert first["summary"]["completed"] == 1

        resumed = migrate_legacy_storage(
            db,
            settings,
            checkpoint_path=checkpoint,
        )
        assert resumed["summary"] == {
            "completed": 3,
            "skipped": 0,
            "failed": 0,
        }, resumed
        assert len(db.scalars(select(StoredObject)).all()) == 3
        assert all(
            row.storage_path is None and row.storage_object_id
            for row in (
                db.scalars(select(Document)).all()
                + db.scalars(select(EvidenceAsset)).all()
                + db.scalars(select(MemoryExportArtifact)).all()
            )
        )

        again = migrate_legacy_storage(
            db,
            settings,
            checkpoint_path=checkpoint,
        )
        assert again["summary"]["completed"] == 3
        assert len(db.scalars(select(StoredObject)).all()) == 3
        checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
        serialized = json.dumps(checkpoint_payload)
        assert str(sources) not in serialized

        missing = db.scalars(select(StoredObject)).first()
        StorageService(db, settings).backend.delete(missing.object_key)
        reconciled = reconcile_storage(db, settings)
        assert reconciled["summary"]["missing"] == 1
        db.refresh(missing)
        assert missing.status == "missing"


def test_fresh_schema_contains_storage_locator_indexes_and_foreign_keys(tmp_path):
    schema_engine = create_engine(
        f"sqlite:///{(tmp_path / 'fresh-storage-schema.db').as_posix()}"
    )
    Base.metadata.create_all(schema_engine)
    inspector = inspect(schema_engine)
    for table_name in (
        "documents",
        "evidence_assets",
        "memory_export_artifacts",
    ):
        indexes = {item["name"] for item in inspector.get_indexes(table_name)}
        assert f"ix_{table_name}_storage_object" in indexes
        assert any(
            item["referred_table"] == "stored_objects"
            and item["constrained_columns"] == ["storage_object_id"]
            for item in inspector.get_foreign_keys(table_name)
        )
    schema_engine.dispose()


def test_storage_schema_migration_preserves_legacy_paths_and_downgrades(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "storage-schema.db"
    database_url = f"sqlite:///{database.as_posix()}"
    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "MODEL_PROVIDER": "mock",
        "MEMORY_IDENTITY_SECRET": "storage-migration-test-secret",
    }

    def alembic(*arguments: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    alembic("upgrade", "20260728_0011")
    migration_engine = create_engine(database_url)
    with migration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO projects "
                "(id, organization_id, name, domain, language, created_at) "
                "VALUES "
                "('storage-project', :organization_id, 'Storage', 'test', "
                "'en', '2026-07-28 00:00:00')"
            ),
            {"organization_id": LEGACY_ORGANIZATION_ID},
        )
        connection.execute(
            text(
                "INSERT INTO documents "
                "(id, organization_id, project_id, filename, content_type, "
                "storage_path, content_text, page_map, parse_warnings, "
                "char_count, created_at) VALUES "
                "('legacy-document', :organization_id, 'storage-project', "
                "'paper.txt', 'text/plain', '/legacy/paper.txt', 'legacy', "
                "'[]', '[]', 6, '2026-07-28 00:00:00')"
            ),
            {"organization_id": LEGACY_ORGANIZATION_ID},
        )

    alembic("upgrade", "head")
    inspector = inspect(migration_engine)
    assert "stored_objects" in inspector.get_table_names()
    assert "storage_object_id" in {
        column["name"] for column in inspector.get_columns("documents")
    }
    with migration_engine.connect() as connection:
        migrated = connection.execute(
            text(
                "SELECT storage_path, storage_object_id FROM documents "
                "WHERE id = 'legacy-document'"
            )
        ).one()
        assert migrated.storage_path == "/legacy/paper.txt"
        assert migrated.storage_object_id is None

    alembic("downgrade", "20260728_0011")
    inspector = inspect(migration_engine)
    assert "stored_objects" not in inspector.get_table_names()
    assert "storage_object_id" not in {
        column["name"] for column in inspector.get_columns("documents")
    }
    with migration_engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT COUNT(*) FROM documents "
                "WHERE id = 'legacy-document' "
                "AND storage_path = '/legacy/paper.txt'"
            )
        ) == 1
    migration_engine.dispose()
