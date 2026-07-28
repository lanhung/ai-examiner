"""Add and backfill direct tenant ownership columns.

Revision ID: 20260728_0010
Revises: 20260727_0009
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260728_0010"
down_revision = "20260727_0009"
branch_labels = None
depends_on = None

LEGACY_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"

GLOBAL_OR_TENANT_TABLES = (
    "scenario_templates",
    "scenario_template_versions",
    "template_validation_runs",
    "prompt_versions",
    "concepts",
)

REQUIRED_TENANT_TABLES = (
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

ALL_OWNED_TABLES = GLOBAL_OR_TENANT_TABLES + REQUIRED_TENANT_TABLES


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {
        item["name"]
        for item in inspect(op.get_bind()).get_columns(table_name)
    }


def _update_from_parent(
    child: str,
    parent: str,
    child_fk: str,
) -> None:
    op.execute(
        sa.text(
            f"UPDATE {child} SET organization_id = "
            f"(SELECT organization_id FROM {parent} "
            f"WHERE {parent}.id = {child}.{child_fk}) "
            "WHERE organization_id IS NULL"
        )
    )


def upgrade() -> None:
    existing = _tables()
    for table_name in ALL_OWNED_TABLES:
        if table_name not in existing or "organization_id" in _columns(table_name):
            continue
        op.add_column(
            table_name,
            sa.Column("organization_id", sa.String(36), nullable=True),
        )
        op.create_index(
            f"ix_{table_name}_organization",
            table_name,
            ["organization_id"],
        )

    if (
        "background_jobs" in existing
        and "actor_principal_id" not in _columns("background_jobs")
    ):
        op.add_column(
            "background_jobs",
            sa.Column("actor_principal_id", sa.String(36), nullable=True),
        )

    if "scenario_templates" in existing:
        op.execute(
            sa.text(
                "UPDATE scenario_templates "
                "SET organization_id = :legacy "
                "WHERE organization_id IS NULL AND owner_scope <> 'built_in'"
            ).bindparams(legacy=LEGACY_ORGANIZATION_ID)
        )
    if "scenario_template_versions" in existing:
        _update_from_parent(
            "scenario_template_versions",
            "scenario_templates",
            "template_id",
        )
    if "template_validation_runs" in existing:
        _update_from_parent(
            "template_validation_runs",
            "scenario_template_versions",
            "template_version_id",
        )
    if "concepts" in existing:
        op.execute(
            sa.text(
                "UPDATE concepts SET organization_id = :legacy "
                "WHERE organization_id IS NULL"
            ).bindparams(legacy=LEGACY_ORGANIZATION_ID)
        )

    project_children = {
        "project_template_bindings": "project_id",
        "documents": "project_id",
        "blueprints": "project_id",
        "exam_sessions": "project_id",
        "golden_datasets": "project_id",
        "benchmark_runs": "project_id",
        "evidence_assets": "project_id",
        "visual_analyses": "project_id",
        "joint_analyses": "project_id",
        "voice_sessions": "project_id",
        "knowledge_units": "project_id",
        "learner_subjects": "project_id",
    }
    for child, child_fk in project_children.items():
        if child in existing:
            _update_from_parent(child, "projects", child_fk)

    for child, parent, child_fk in (
        ("turns", "exam_sessions", "session_id"),
        ("expert_ratings", "golden_datasets", "golden_dataset_id"),
        ("voice_events", "voice_sessions", "voice_session_id"),
        ("question_knowledge_units", "knowledge_units", "knowledge_unit_id"),
        (
            "knowledge_unit_concept_maps",
            "knowledge_units",
            "knowledge_unit_id",
        ),
        ("knowledge_states", "exam_sessions", "session_id"),
        ("knowledge_evidence_events", "exam_sessions", "session_id"),
        ("adaptive_decisions", "exam_sessions", "session_id"),
    ):
        if child in existing:
            _update_from_parent(child, parent, child_fk)

    if "usage_events" in existing:
        _update_from_parent("usage_events", "projects", "project_id")
    if "background_jobs" in existing:
        _update_from_parent("background_jobs", "projects", "project_id")

    if "learner_identities" in existing:
        op.execute(
            sa.text(
                "UPDATE learner_identities SET organization_id = COALESCE("
                "(SELECT learner_subjects.organization_id "
                "FROM learner_identity_links "
                "JOIN learner_subjects ON learner_subjects.id = "
                "learner_identity_links.learner_subject_id "
                "WHERE learner_identity_links.learner_identity_id = "
                "learner_identities.id LIMIT 1), :legacy) "
                "WHERE organization_id IS NULL"
            ).bindparams(legacy=LEGACY_ORGANIZATION_ID)
        )

    identity_children = {
        "learner_identity_links": "learner_identity_id",
        "learner_concept_states": "learner_identity_id",
        "retest_plans": "learner_identity_id",
        "learner_preferences": "learner_identity_id",
        "memory_export_artifacts": "learner_identity_id",
        "memory_deletion_audits": "learner_identity_id",
    }
    for child, child_fk in identity_children.items():
        if child in existing:
            _update_from_parent(
                child,
                "learner_identities",
                child_fk,
            )

    if "learner_memory_events" in existing:
        op.execute(
            sa.text(
                "UPDATE learner_memory_events SET organization_id = COALESCE("
                "(SELECT organization_id FROM learner_identities "
                "WHERE id = learner_memory_events.learner_identity_id), "
                "(SELECT organization_id FROM learner_subjects "
                "WHERE id = learner_memory_events.learner_subject_id), "
                "(SELECT organization_id FROM knowledge_evidence_events "
                "WHERE id = learner_memory_events.source_evidence_event_id), "
                ":legacy) WHERE organization_id IS NULL"
            ).bindparams(legacy=LEGACY_ORGANIZATION_ID)
        )
    if "retest_items" in existing:
        _update_from_parent(
            "retest_items",
            "retest_plans",
            "retest_plan_id",
        )

    for table_name in REQUIRED_TENANT_TABLES:
        if table_name not in existing:
            continue
        op.execute(
            sa.text(
                f"UPDATE {table_name} SET organization_id = :legacy "
                "WHERE organization_id IS NULL"
            ).bindparams(legacy=LEGACY_ORGANIZATION_ID)
        )
        missing = int(
            op.get_bind().scalar(
                sa.text(
                    f"SELECT COUNT(*) FROM {table_name} "
                    "WHERE organization_id IS NULL"
                )
            )
            or 0
        )
        if missing:
            raise RuntimeError(
                f"Tenant ownership backfill incomplete for {table_name}: {missing}"
            )


def downgrade() -> None:
    existing = _tables()
    if (
        "background_jobs" in existing
        and "actor_principal_id" in _columns("background_jobs")
    ):
        with op.batch_alter_table("background_jobs") as batch:
            batch.drop_column("actor_principal_id")
    for table_name in reversed(ALL_OWNED_TABLES):
        if table_name not in existing or "organization_id" not in _columns(table_name):
            continue
        inspector = inspect(op.get_bind())
        indexes = {
            item["name"]: tuple(item.get("column_names") or ())
            for item in inspector.get_indexes(table_name)
        }
        index_name = f"ix_{table_name}_organization"
        if index_name in indexes:
            op.drop_index(index_name, table_name=table_name)
        for partial_name in (
            "uq_scenario_template_global_slug",
            "uq_prompt_global_name_version",
            "uq_concept_global_namespace_key",
        ):
            if partial_name in indexes:
                op.drop_index(partial_name, table_name=table_name)
        with op.batch_alter_table(table_name) as batch:
            for constraint in inspector.get_unique_constraints(table_name):
                if (
                    "organization_id"
                    in tuple(constraint.get("column_names") or ())
                    and constraint.get("name")
                ):
                    batch.drop_constraint(
                        constraint["name"],
                        type_="unique",
                    )
            for constraint in inspector.get_foreign_keys(table_name):
                if (
                    "organization_id"
                    in tuple(constraint.get("constrained_columns") or ())
                    and constraint.get("name")
                ):
                    batch.drop_constraint(
                        constraint["name"],
                        type_="foreignkey",
                    )
            batch.drop_column("organization_id")
