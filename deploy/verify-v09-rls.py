from __future__ import annotations

import json
import os
from uuid import uuid4

from sqlalchemy import create_engine, inspect, text

from ai_examiner.enterprise_constants import LEGACY_ORGANIZATION_ID

REQUIRED_TENANT_TABLES = (
    "projects",
    "project_template_bindings",
    "documents",
    "blueprints",
    "exam_sessions",
    "turns",
    "usage_events",
    "golden_datasets",
    "benchmark_runs",
    "expert_ratings",
    "evidence_assets",
    "visual_analyses",
    "background_jobs",
    "joint_analyses",
    "voice_sessions",
    "voice_events",
    "knowledge_units",
    "question_knowledge_units",
    "learner_subjects",
    "learner_identities",
    "learner_identity_links",
    "knowledge_unit_concept_maps",
    "learner_memory_events",
    "learner_concept_states",
    "retest_plans",
    "retest_items",
    "learner_preferences",
    "memory_export_artifacts",
    "memory_deletion_audits",
    "knowledge_states",
    "knowledge_evidence_events",
    "adaptive_decisions",
)

RLS_TABLES = REQUIRED_TENANT_TABLES + (
    "organizations",
    "organization_memberships",
    "scenario_templates",
    "scenario_template_versions",
    "template_validation_runs",
    "prompt_versions",
    "concepts",
)


def verify() -> dict:
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url, future=True)
    if engine.dialect.name != "postgresql":
        raise RuntimeError("The v0.9 RLS verification requires PostgreSQL")

    inspector = inspect(engine)
    for table_name in REQUIRED_TENANT_TABLES:
        columns = {
            column["name"]: column
            for column in inspector.get_columns(table_name)
        }
        organization = columns.get("organization_id")
        if organization is None or organization["nullable"]:
            raise RuntimeError(
                f"{table_name}.organization_id must exist and be non-null"
            )

    organization_a = str(uuid4())
    organization_b = str(uuid4())
    project_a = str(uuid4())
    project_b = str(uuid4())
    cross_tenant_project = str(uuid4())
    result: dict[str, object] = {}

    with engine.connect() as connection:
        policies = int(
            connection.scalar(
                text(
                    "SELECT COUNT(*) FROM pg_policies "
                    "WHERE schemaname = current_schema() "
                    "AND policyname = 'tenant_isolation' "
                    "AND tablename = ANY(:tables)"
                ),
                {"tables": list(RLS_TABLES)},
            )
            or 0
        )
        if policies != len(RLS_TABLES):
            raise RuntimeError(
                f"Expected {len(RLS_TABLES)} tenant policies, found {policies}"
            )

        transaction = connection.begin_nested()
        connection.execute(
            text(
                "INSERT INTO organizations "
                "(id, slug, display_name, status, version, created_at, updated_at) "
                "VALUES "
                "(:a, :slug_a, 'RLS A', 'active', 1, now(), now()), "
                "(:b, :slug_b, 'RLS B', 'active', 1, now(), now())"
            ),
            {
                "a": organization_a,
                "b": organization_b,
                "slug_a": f"rls-a-{organization_a}",
                "slug_b": f"rls-b-{organization_b}",
            },
        )
        connection.execute(
            text(
                "INSERT INTO projects "
                "(id, organization_id, name, domain, language, created_at) "
                "VALUES "
                "(:project_a, :a, 'Project A', 'test', 'en', now()), "
                "(:project_b, :b, 'Project B', 'test', 'en', now())"
            ),
            {
                "project_a": project_a,
                "project_b": project_b,
                "a": organization_a,
                "b": organization_b,
            },
        )

        connection.execute(text("SET LOCAL ROLE ai_examiner_runtime"))
        missing_context_count = int(
            connection.scalar(text("SELECT COUNT(*) FROM projects")) or 0
        )
        if missing_context_count:
            raise RuntimeError("Missing tenant context exposed protected projects")

        connection.execute(
            text(
                "SELECT set_config('app.organization_id', :organization_id, true)"
            ),
            {"organization_id": organization_a},
        )
        visible_a = connection.execute(
            text("SELECT id FROM projects ORDER BY id")
        ).scalars().all()
        if visible_a != [project_a]:
            raise RuntimeError(f"Organization A visibility mismatch: {visible_a}")

        connection.execute(
            text(
                "SELECT set_config('app.organization_id', :organization_id, true)"
            ),
            {"organization_id": organization_b},
        )
        visible_b = connection.execute(
            text("SELECT id FROM projects ORDER BY id")
        ).scalars().all()
        if visible_b != [project_b]:
            raise RuntimeError(f"Organization B visibility mismatch: {visible_b}")

        cross_tenant_write_blocked = False
        savepoint = connection.begin_nested()
        try:
            connection.execute(
                text(
                    "INSERT INTO projects "
                    "(id, organization_id, name, domain, language, created_at) "
                    "VALUES (:id, :organization_id, 'Cross tenant', "
                    "'test', 'en', now())"
                ),
                {
                    "id": cross_tenant_project,
                    "organization_id": organization_a,
                },
            )
            savepoint.commit()
        except Exception:
            savepoint.rollback()
            cross_tenant_write_blocked = True
        if not cross_tenant_write_blocked:
            raise RuntimeError("Cross-tenant write was not blocked by RLS")

        transaction.rollback()
        result = {
            "status": "passed",
            "policy_count": policies,
            "protected_table_count": len(REQUIRED_TENANT_TABLES),
            "missing_context_count": missing_context_count,
            "organization_a_visible": len(visible_a),
            "organization_b_visible": len(visible_b),
            "cross_tenant_write_blocked": cross_tenant_write_blocked,
            "legacy_organization": LEGACY_ORGANIZATION_ID,
        }
    engine.dispose()
    return result


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
