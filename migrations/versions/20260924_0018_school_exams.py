"""Published teacher exams and individually authorized student attempts."""

import sqlalchemy as sa
from alembic import op

from ai_examiner.db import Base

revision = "20260924_0018"
down_revision = "20260810_0017"
branch_labels = None
depends_on = None

TABLES = ("teaching_grants", "published_exams", "exam_papers", "school_attempts")


def upgrade():
    from ai_examiner import models  # noqa: F401

    bind = op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=True)
    if bind.dialect.name != "postgresql":
        return
    principal = "NULLIF(current_setting('app.principal_id', true), '')"
    tenant = "organization_id = NULLIF(current_setting('app.organization_id', true), '')"
    def admin(table):
        return (
            f"EXISTS (SELECT 1 FROM organization_memberships m WHERE "
            f"m.organization_id = {table}.organization_id AND m.principal_id = {principal} "
            "AND m.status = 'active' AND m.role IN ('owner', 'admin'))"
        )
    policies = {
        "teaching_grants": (f"principal_id = {principal} OR {admin('teaching_grants')}", None),
        "published_exams": (
            f"{principal} IS NOT NULL AND (status = 'published' OR teacher_id = {principal} "
            f"OR EXISTS (SELECT 1 FROM school_attempts a WHERE a.exam_id = published_exams.id "
            f"AND a.student_id = {principal}) OR {admin('published_exams')})",
            f"teacher_id = {principal} AND {tenant}",
        ),
        "exam_papers": (tenant, tenant),
        "school_attempts": (
            f"student_id = {principal} OR teacher_id = {principal} OR {admin('school_attempts')}",
            f"({tenant}) AND (student_id = {principal} OR teacher_id = {principal})",
        ),
    }
    for name, (read, write) in policies.items():
        bind.execute(sa.text(f"REVOKE ALL ON TABLE {name} FROM PUBLIC"))
        bind.execute(sa.text(f"REVOKE ALL ON TABLE {name} FROM ai_examiner_runtime"))
        permissions = "SELECT, INSERT, UPDATE" if write else "SELECT"
        bind.execute(sa.text(f"GRANT {permissions} ON {name} TO ai_examiner_runtime"))
        bind.execute(sa.text(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY"))
        bind.execute(sa.text(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY"))
        bind.execute(sa.text(
            f"CREATE POLICY school_read ON {name} FOR SELECT TO ai_examiner_runtime USING ({read})"
        ))
        if write:
            bind.execute(sa.text(
                f"CREATE POLICY school_insert ON {name} FOR INSERT TO ai_examiner_runtime "
                f"WITH CHECK ({write})"
            ))
            bind.execute(sa.text(
                f"CREATE POLICY school_update ON {name} FOR UPDATE TO ai_examiner_runtime "
                f"USING ({write}) WITH CHECK ({write})"
            ))


def downgrade():
    for name in reversed(TABLES):
        op.drop_table(name)
