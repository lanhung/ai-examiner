"""Enforce tenant ownership and PostgreSQL row-level security.

Revision ID: 20260728_0011
Revises: 20260728_0010
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260728_0011"
down_revision = "20260728_0010"
branch_labels = None
depends_on = None

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

IDENTITY_CONTROL_TABLES = (
    "principals",
    "oidc_login_transactions",
    "browser_auth_sessions",
)

COMPOSITE_LINKS = (
    ("documents", "project_id", "projects", "fk_tenant_document_project"),
    ("blueprints", "project_id", "projects", "fk_tenant_blueprint_project"),
    ("blueprints", "document_id", "documents", "fk_tenant_blueprint_document"),
    ("exam_sessions", "project_id", "projects", "fk_tenant_session_project"),
    ("exam_sessions", "blueprint_id", "blueprints", "fk_tenant_session_blueprint"),
    ("turns", "session_id", "exam_sessions", "fk_tenant_turn_session"),
    ("golden_datasets", "project_id", "projects", "fk_tenant_dataset_project"),
    ("golden_datasets", "document_id", "documents", "fk_tenant_dataset_document"),
    ("benchmark_runs", "project_id", "projects", "fk_tenant_benchmark_project"),
    (
        "benchmark_runs",
        "golden_dataset_id",
        "golden_datasets",
        "fk_tenant_benchmark_dataset",
    ),
    (
        "expert_ratings",
        "golden_dataset_id",
        "golden_datasets",
        "fk_tenant_rating_dataset",
    ),
    ("evidence_assets", "project_id", "projects", "fk_tenant_evidence_project"),
    (
        "evidence_assets",
        "document_id",
        "documents",
        "fk_tenant_evidence_document",
    ),
    (
        "visual_analyses",
        "evidence_asset_id",
        "evidence_assets",
        "fk_tenant_visual_evidence",
    ),
    ("joint_analyses", "project_id", "projects", "fk_tenant_joint_project"),
    ("voice_sessions", "project_id", "projects", "fk_tenant_voice_project"),
    (
        "voice_sessions",
        "exam_session_id",
        "exam_sessions",
        "fk_tenant_voice_session",
    ),
    (
        "voice_events",
        "voice_session_id",
        "voice_sessions",
        "fk_tenant_voice_event_session",
    ),
    ("knowledge_units", "project_id", "projects", "fk_tenant_unit_project"),
    (
        "knowledge_units",
        "blueprint_id",
        "blueprints",
        "fk_tenant_unit_blueprint",
    ),
    (
        "question_knowledge_units",
        "knowledge_unit_id",
        "knowledge_units",
        "fk_tenant_question_unit",
    ),
    ("learner_subjects", "project_id", "projects", "fk_tenant_subject_project"),
    (
        "learner_identity_links",
        "learner_identity_id",
        "learner_identities",
        "fk_tenant_identity_link_identity",
    ),
    (
        "learner_identity_links",
        "learner_subject_id",
        "learner_subjects",
        "fk_tenant_identity_link_subject",
    ),
    (
        "learner_concept_states",
        "learner_identity_id",
        "learner_identities",
        "fk_tenant_concept_state_identity",
    ),
    (
        "retest_plans",
        "learner_identity_id",
        "learner_identities",
        "fk_tenant_retest_plan_identity",
    ),
    ("retest_items", "retest_plan_id", "retest_plans", "fk_tenant_retest_item_plan"),
    (
        "learner_preferences",
        "learner_identity_id",
        "learner_identities",
        "fk_tenant_preference_identity",
    ),
    (
        "memory_export_artifacts",
        "learner_identity_id",
        "learner_identities",
        "fk_tenant_export_identity",
    ),
    (
        "knowledge_states",
        "session_id",
        "exam_sessions",
        "fk_tenant_knowledge_state_session",
    ),
    (
        "knowledge_states",
        "knowledge_unit_id",
        "knowledge_units",
        "fk_tenant_knowledge_state_unit",
    ),
    (
        "knowledge_evidence_events",
        "session_id",
        "exam_sessions",
        "fk_tenant_evidence_event_session",
    ),
    (
        "knowledge_evidence_events",
        "turn_id",
        "turns",
        "fk_tenant_evidence_event_turn",
    ),
    (
        "knowledge_evidence_events",
        "knowledge_unit_id",
        "knowledge_units",
        "fk_tenant_evidence_event_unit",
    ),
    (
        "adaptive_decisions",
        "session_id",
        "exam_sessions",
        "fk_tenant_decision_session",
    ),
)


def _constraint_names(table_name: str) -> set[str]:
    inspector = inspect(op.get_bind())
    names = {
        item["name"]
        for item in inspector.get_unique_constraints(table_name)
        if item.get("name")
    }
    names.update(
        item["name"]
        for item in inspector.get_foreign_keys(table_name)
        if item.get("name")
    )
    return names


def _has_foreign_key(
    table_name: str,
    constrained_columns: tuple[str, ...],
    referred_table: str,
    referred_columns: tuple[str, ...],
) -> bool:
    return any(
        tuple(item.get("constrained_columns") or ()) == constrained_columns
        and item.get("referred_table") == referred_table
        and tuple(item.get("referred_columns") or ()) == referred_columns
        for item in inspect(op.get_bind()).get_foreign_keys(table_name)
    )


def _index_names(table_name: str) -> set[str]:
    return {
        item["name"]
        for item in inspect(op.get_bind()).get_indexes(table_name)
        if item.get("name")
    }


def _drop_unique_for_columns(
    table_name: str,
    columns: tuple[str, ...],
) -> None:
    for constraint in inspect(op.get_bind()).get_unique_constraints(table_name):
        if tuple(constraint.get("column_names") or ()) != columns:
            continue
        name = constraint.get("name")
        if name:
            op.drop_constraint(name, table_name, type_="unique")


def _postgres_rls() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_roles "
            "WHERE rolname = 'ai_examiner_runtime') THEN "
            "CREATE ROLE ai_examiner_runtime NOLOGIN NOSUPERUSER "
            "NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS; "
            "END IF; END $$"
        )
    )
    bind.execute(sa.text("GRANT USAGE ON SCHEMA public TO ai_examiner_runtime"))
    for table_name in IDENTITY_CONTROL_TABLES:
        bind.execute(
            sa.text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
                f"{table_name} TO ai_examiner_runtime"
            )
        )
    for table_name in ("organizations", "organization_memberships") + ALL_OWNED_TABLES + (
        "projects",
    ):
        bind.execute(
            sa.text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
                f"{table_name} TO ai_examiner_runtime"
            )
        )
        bind.execute(sa.text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))
        bind.execute(sa.text(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY"))
        bind.execute(
            sa.text(
                f"DROP POLICY IF EXISTS tenant_isolation ON {table_name}"
            )
        )
        if table_name == "organizations":
            using = (
                "id = NULLIF(current_setting('app.organization_id', true), '')"
            )
        elif table_name in GLOBAL_OR_TENANT_TABLES:
            using = (
                "organization_id IS NULL OR organization_id = "
                "NULLIF(current_setting('app.organization_id', true), '')"
            )
        else:
            using = (
                "organization_id = "
                "NULLIF(current_setting('app.organization_id', true), '')"
            )
        check = (
            "organization_id = "
            "NULLIF(current_setting('app.organization_id', true), '')"
            if table_name != "organizations"
            else "id = NULLIF(current_setting('app.organization_id', true), '')"
        )
        bind.execute(
            sa.text(
                f"CREATE POLICY tenant_isolation ON {table_name} "
                f"FOR ALL TO ai_examiner_runtime USING ({using}) "
                f"WITH CHECK ({check})"
            )
        )
def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    for table_name in REQUIRED_TENANT_TABLES:
        with op.batch_alter_table(table_name) as batch:
            batch.alter_column(
                "organization_id",
                existing_type=sa.String(36),
                nullable=False,
            )

    if dialect != "postgresql":
        return

    for table_name in ALL_OWNED_TABLES:
        fk_name = f"fk_{table_name}_organization"
        if not _has_foreign_key(
            table_name,
            ("organization_id",),
            "organizations",
            ("id",),
        ):
            op.create_foreign_key(
                fk_name,
                table_name,
                "organizations",
                ["organization_id"],
                ["id"],
                ondelete="RESTRICT",
            )

    if not _has_foreign_key(
        "background_jobs",
        ("actor_principal_id",),
        "principals",
        ("id",),
    ):
        op.create_foreign_key(
            "fk_background_jobs_actor",
            "background_jobs",
            "principals",
            ["actor_principal_id"],
            ["id"],
            ondelete="SET NULL",
        )

    _drop_unique_for_columns("scenario_templates", ("slug",))
    _drop_unique_for_columns("learner_identities", ("opaque_key_hash",))
    _drop_unique_for_columns("concepts", ("namespace", "canonical_key"))
    for table_name, name, columns in (
        (
            "scenario_templates",
            "uq_scenario_template_organization_slug",
            ["organization_id", "slug"],
        ),
        (
            "prompt_versions",
            "uq_prompt_organization_name_version",
            ["organization_id", "name", "version"],
        ),
        (
            "learner_identities",
            "uq_learner_identity_organization_hash",
            ["organization_id", "opaque_key_hash"],
        ),
        (
            "concepts",
            "uq_concept_organization_namespace_key",
            ["organization_id", "namespace", "canonical_key"],
        ),
    ):
        if name not in _constraint_names(table_name):
            op.create_unique_constraint(name, table_name, columns)
    for table_name, name, columns in (
        (
            "scenario_templates",
            "uq_scenario_template_global_slug",
            ["slug"],
        ),
        (
            "prompt_versions",
            "uq_prompt_global_name_version",
            ["name", "version"],
        ),
        (
            "concepts",
            "uq_concept_global_namespace_key",
            ["namespace", "canonical_key"],
        ),
    ):
        if name not in _index_names(table_name):
            op.create_index(
                name,
                table_name,
                columns,
                unique=True,
                postgresql_where=sa.text("organization_id IS NULL"),
            )

    parent_tables = {parent for _, _, parent, _ in COMPOSITE_LINKS}
    for table_name in sorted(parent_tables):
        name = f"uq_{table_name}_organization_id"
        if name not in _constraint_names(table_name):
            op.create_unique_constraint(
                name,
                table_name,
                ["organization_id", "id"],
            )

    for child, child_fk, parent, name in COMPOSITE_LINKS:
        if name in _constraint_names(child):
            continue
        op.create_foreign_key(
            name,
            child,
            parent,
            ["organization_id", child_fk],
            ["organization_id", "id"],
        )

    _postgres_rls()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table_name in (
            "organizations",
            "organization_memberships",
        ) + ALL_OWNED_TABLES + ("projects",):
            bind.execute(
                sa.text(
                    f"DROP POLICY IF EXISTS tenant_isolation ON {table_name}"
                )
            )
            bind.execute(sa.text(f"ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY"))
            bind.execute(sa.text(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY"))
        for child, _, _, name in reversed(COMPOSITE_LINKS):
            if name in _constraint_names(child):
                op.drop_constraint(name, child, type_="foreignkey")
        for table_name in sorted(
            {parent for _, _, parent, _ in COMPOSITE_LINKS},
            reverse=True,
        ):
            name = f"uq_{table_name}_organization_id"
            if name in _constraint_names(table_name):
                op.drop_constraint(name, table_name, type_="unique")
        for table_name in reversed(ALL_OWNED_TABLES):
            name = f"fk_{table_name}_organization"
            if name in _constraint_names(table_name):
                op.drop_constraint(name, table_name, type_="foreignkey")
        if "fk_background_jobs_actor" in _constraint_names("background_jobs"):
            op.drop_constraint(
                "fk_background_jobs_actor",
                "background_jobs",
                type_="foreignkey",
            )
        for table_name, name in (
            ("scenario_templates", "uq_scenario_template_global_slug"),
            ("prompt_versions", "uq_prompt_global_name_version"),
            ("concepts", "uq_concept_global_namespace_key"),
        ):
            op.drop_index(name, table_name=table_name)
        for table_name, name in (
            (
                "scenario_templates",
                "uq_scenario_template_organization_slug",
            ),
            ("prompt_versions", "uq_prompt_organization_name_version"),
            (
                "learner_identities",
                "uq_learner_identity_organization_hash",
            ),
            ("concepts", "uq_concept_organization_namespace_key"),
        ):
            if name in _constraint_names(table_name):
                op.drop_constraint(name, table_name, type_="unique")
        op.create_unique_constraint(
            "uq_concept_namespace_key",
            "concepts",
            ["namespace", "canonical_key"],
        )
        op.create_unique_constraint(
            "uq_scenario_template_slug_legacy",
            "scenario_templates",
            ["slug"],
        )
        op.create_unique_constraint(
            "uq_learner_identity_hash_legacy",
            "learner_identities",
            ["opaque_key_hash"],
        )

    for table_name in REQUIRED_TENANT_TABLES:
        with op.batch_alter_table(table_name) as batch:
            batch.alter_column(
                "organization_id",
                existing_type=sa.String(36),
                nullable=True,
            )
