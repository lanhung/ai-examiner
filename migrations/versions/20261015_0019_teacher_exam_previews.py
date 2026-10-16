"""Isolated teacher exam previews, with owner-only PostgreSQL RLS."""

import sqlalchemy as sa
from alembic import op

revision = "20261015_0019"
down_revision = "20260924_0018"
branch_labels = None
depends_on = None


def _create_table():
    op.create_table(
        "teacher_exam_previews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("exam_id", sa.String(36), sa.ForeignKey("published_exams.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("teacher_id", sa.String(36), sa.ForeignKey("principals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("pending", sa.JSON(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("reviewed_score", sa.Float(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("review_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("exam_id", "teacher_id", name="uq_teacher_exam_preview"),
        sa.CheckConstraint("status IN ('active', 'grading', 'needs_review', 'completed')", name="ck_teacher_preview_status"),
        sa.CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_teacher_preview_score"),
        sa.CheckConstraint("reviewed_score IS NULL OR (reviewed_score >= 0 AND reviewed_score <= 100)", name="ck_teacher_preview_review_score"),
    )


def upgrade():
    bind = op.get_bind()
    # The legacy fresh-install migration bootstraps current model metadata.
    if not sa.inspect(bind).has_table("teacher_exam_previews"):
        _create_table()
    if bind.dialect.name != "postgresql":
        return
    principal = "NULLIF(current_setting('app.principal_id', true), '')"
    tenant = "NULLIF(current_setting('app.organization_id', true), '')"
    owner = f"teacher_id = {principal} AND organization_id = {tenant}"
    bind.execute(sa.text("REVOKE ALL ON TABLE teacher_exam_previews FROM PUBLIC"))
    bind.execute(sa.text("GRANT SELECT, INSERT, UPDATE ON teacher_exam_previews TO ai_examiner_runtime"))
    bind.execute(sa.text("ALTER TABLE teacher_exam_previews ENABLE ROW LEVEL SECURITY"))
    bind.execute(sa.text("ALTER TABLE teacher_exam_previews FORCE ROW LEVEL SECURITY"))
    bind.execute(sa.text(
        "CREATE POLICY teacher_preview_owner ON teacher_exam_previews "
        f"TO ai_examiner_runtime USING ({owner}) WITH CHECK ({owner})"
    ))


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM teacher_exam_previews")):
        raise RuntimeError("Preview records exist; back them up before an explicit data-removal migration")
    op.drop_table("teacher_exam_previews")
