-- Synthetic fixtures only. This script refuses the live deployment database.
\set ON_ERROR_STOP on
DO $$ BEGIN
  IF current_database() NOT LIKE 'aiex_school_%_test' THEN
    RAISE EXCEPTION 'Refusing non-disposable database';
  END IF;
END $$;
BEGIN;
INSERT INTO organizations (id, slug, display_name, status, version, created_at, updated_at)
VALUES ('school-teacher-org', 'school-teacher-test', 'Teacher', 'active', 1, now(), now()),
       ('school-student-org', 'school-student-test', 'Student', 'active', 1, now(), now());
INSERT INTO principals (id, issuer, subject, status, created_at, updated_at)
VALUES ('school-teacher', 'synthetic-school', 'teacher', 'active', now(), now()),
       ('school-student-a', 'synthetic-school', 'a', 'active', now(), now()),
       ('school-student-b', 'synthetic-school', 'b', 'active', now(), now());
INSERT INTO organization_memberships
  (id, organization_id, principal_id, role, status, version, created_at, updated_at)
VALUES ('school-t-member', 'school-teacher-org', 'school-teacher', 'examiner', 'active', 1, now(), now()),
       ('school-a-member', 'school-student-org', 'school-student-a', 'examiner', 'active', 1, now(), now()),
       ('school-b-member', 'school-student-org', 'school-student-b', 'examiner', 'active', 1, now(), now());
INSERT INTO projects (id, organization_id, name, domain, language, data_classification, created_at)
VALUES ('school-project', 'school-teacher-org', 'Synthetic', 'research_defense', 'zh-CN', 'internal', now());
INSERT INTO documents (id, organization_id, project_id, filename, content_type, content_text,
                       page_map, parse_warnings, char_count, created_at)
VALUES ('school-document', 'school-teacher-org', 'school-project', 'test.txt', 'text/plain',
        'Synthetic paper', '[]', '[]', 15, now());
INSERT INTO teaching_grants (principal_id, organization_id, active, updated_at)
VALUES ('school-teacher', 'school-teacher-org', true, now());
INSERT INTO published_exams (id, teacher_id, organization_id, publish_key, request_digest,
                            title, instructions, teacher_name, material_name, material_text,
                            question_count, status, created_at)
VALUES ('school-exam', 'school-teacher', 'school-teacher-org', 'school-key', repeat('a',64),
        'Synthetic exam', '', 'Teacher', 'test.txt', 'Synthetic paper', 1, 'published', now());
INSERT INTO exam_papers (exam_id, organization_id, project_id, blueprint_id, document_id, questions, profile)
VALUES ('school-exam', 'school-teacher-org', 'school-project', 'school-blueprint',
        'school-document', '[{"text":"Question","expected_points":["secret-key"]}]', 'qwen:qwen-plus');
INSERT INTO school_attempts (id, exam_id, organization_id, teacher_id, student_id, student_name,
                            student_number, status, answers, review_version, created_at, updated_at)
VALUES ('school-a', 'school-exam', 'school-teacher-org', 'school-teacher', 'school-student-a',
        'A', '', 'active', '[]', 0, now(), now()),
       ('school-b', 'school-exam', 'school-teacher-org', 'school-teacher', 'school-student-b',
        'B', '', 'active', '[]', 0, now(), now());
SET LOCAL ROLE ai_examiner_runtime;
SELECT set_config('app.organization_id', '', true), set_config('app.principal_id', '', true);
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM published_exams) OR EXISTS (SELECT 1 FROM school_attempts)
     OR EXISTS (SELECT 1 FROM exam_papers) THEN RAISE EXCEPTION 'Anonymous data leak'; END IF;
END $$;
SELECT set_config('app.principal_id', 'school-student-a', true);
DO $$ BEGIN
  IF (SELECT count(*) FROM published_exams) <> 1 THEN RAISE EXCEPTION 'Catalog unreadable'; END IF;
  IF (SELECT count(*) FROM school_attempts) <> 1 THEN RAISE EXCEPTION 'Student isolation failed'; END IF;
  IF EXISTS (SELECT 1 FROM exam_papers) THEN RAISE EXCEPTION 'Answer key leaked'; END IF;
  IF EXISTS (SELECT 1 FROM teaching_grants) THEN RAISE EXCEPTION 'Teacher grant leaked'; END IF;
  IF has_table_privilege(current_user, 'teaching_grants', 'INSERT') OR
     has_table_privilege(current_user, 'teaching_grants', 'UPDATE') THEN
     RAISE EXCEPTION 'Runtime can self-elevate';
  END IF;
END $$;
SELECT set_config('app.organization_id', 'school-student-org', true);
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM exam_papers) THEN RAISE EXCEPTION 'Cross-tenant key leak'; END IF;
  UPDATE school_attempts SET student_name='forged' WHERE id='school-b';
  IF FOUND THEN RAISE EXCEPTION 'Can change another student'; END IF;
END $$;
SELECT set_config('app.organization_id', 'school-teacher-org', true),
       set_config('app.principal_id', 'school-teacher', true);
DO $$ BEGIN
  IF (SELECT count(*) FROM school_attempts) <> 2 THEN RAISE EXCEPTION 'Teacher grade access failed'; END IF;
  IF (SELECT count(*) FROM exam_papers) <> 1 THEN RAISE EXCEPTION 'Teacher key access failed'; END IF;
END $$;
UPDATE published_exams SET status='closed' WHERE id='school-exam';
SELECT set_config('app.organization_id', '', true),
       set_config('app.principal_id', 'school-student-a', true);
DO $$ BEGIN
  IF (SELECT count(*) FROM published_exams) <> 1 THEN RAISE EXCEPTION 'Lost closed exam history'; END IF;
END $$;
SELECT set_config('app.principal_id', 'unknown', true);
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM published_exams) THEN RAISE EXCEPTION 'Closed exam exposed to newcomer'; END IF;
END $$;
ROLLBACK;
SELECT 'SCHOOL RLS PASS; synthetic data rolled back' AS result;
