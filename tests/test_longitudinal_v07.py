from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from ai_examiner.db import SessionLocal
from ai_examiner.models import (
    Concept,
    LearnerConceptState,
    LearnerIdentity,
    LearnerIdentityLink,
    LearnerMemoryEvent,
    LearnerSubject,
    Project,
    RetestPlan,
)
from ai_examiner.services.longitudinal import LongitudinalStateService


def _memory_fixture(db, *, now: datetime):
    identity = LearnerIdentity(
        opaque_key_hash="a" * 64,
        display_name="Longitudinal learner",
        memory_enabled=True,
        retest_planning_enabled=True,
    )
    evidence = Concept(
        namespace="research",
        canonical_key="evidence-validity",
        title="Evidence validity",
    )
    generalization = Concept(
        namespace="research",
        canonical_key="generalization",
        title="Generalization",
    )
    db.add_all([identity, evidence, generalization])
    db.flush()
    db.add_all(
        [
            LearnerMemoryEvent(
                learner_identity_id=identity.id,
                concept_id=evidence.id,
                event_type="concept_evidence",
                occurred_at=now - timedelta(days=90),
                payload_json={
                    "observation": 0.9,
                    "evidence_weight": 1.0,
                    "assistance_level": "direct",
                    "detected_misconceptions": ["correlation proves causation"],
                },
            ),
            LearnerMemoryEvent(
                learner_identity_id=identity.id,
                concept_id=evidence.id,
                event_type="concept_evidence",
                occurred_at=now - timedelta(days=60),
                payload_json={
                    "observation": 0.6,
                    "evidence_weight": 1.0,
                    "assistance_level": "followup",
                },
            ),
            LearnerMemoryEvent(
                learner_identity_id=identity.id,
                concept_id=generalization.id,
                event_type="concept_evidence",
                occurred_at=now - timedelta(days=120),
                payload_json={
                    "observation": 0.8,
                    "evidence_weight": 1.0,
                    "assistance_level": "direct",
                },
            ),
        ]
    )
    db.flush()
    return identity, evidence, generalization


def test_rebuild_is_deterministic_and_preserves_observation_prediction_boundary():
    now = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)
    with SessionLocal() as db:
        identity, evidence, _ = _memory_fixture(db, now=now)
        service = LongitudinalStateService(db)

        first = service.rebuild(
            identity,
            algorithm_version="evidence-half-life-v1",
            dry_run=True,
            as_of=now,
        )
        second = service.rebuild(
            identity,
            algorithm_version="evidence-half-life-v1",
            dry_run=True,
            as_of=now,
        )
        assert first == second
        evidence_state = next(item for item in first if item["concept_id"] == evidence.id)
        assert evidence_state["predicted_retention"] < evidence_state["observed_mastery"]
        assert evidence_state["independent_evidence_count"] == 1
        assert evidence_state["assisted_evidence_count"] == 1
        assert evidence_state["active_misconceptions"] == [
            "correlation proves causation"
        ]

        no_decay = service.rebuild(
            identity,
            algorithm_version="no-decay-v1",
            dry_run=True,
            as_of=now,
        )
        no_decay_state = next(
            item for item in no_decay if item["concept_id"] == evidence.id
        )
        assert no_decay_state["predicted_retention"] == no_decay_state["observed_mastery"]

        service.rebuild(
            identity,
            algorithm_version="evidence-half-life-v1",
            dry_run=False,
            as_of=now,
        )
        service.rebuild(
            identity,
            algorithm_version="evidence-half-life-v1",
            dry_run=False,
            as_of=now,
        )
        assert db.scalar(select(func.count(LearnerConceptState.id))) == 2
        states = service.states(identity, as_of=now)
        assert all(state["predicted_at"] == now.isoformat() for state in states)

        growth = service.growth(identity, concept_id=evidence.id)
        assert len(growth) == 1
        assert len(growth[0]["points"]) == 2
        assert growth[0]["points"][0]["observed_at"] < growth[0]["points"][1][
            "observed_at"
        ]


def test_longitudinal_api_and_shadow_retest_planner(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        identity, evidence, _ = _memory_fixture(db, now=now)
        identity_id = identity.id
        evidence_id = evidence.id
        db.commit()

    dry_run = client.post(
        f"/api/learner-identities/{identity_id}/memory/rebuild",
        json={"algorithm_version": "fixed-half-life-v1", "dry_run": True},
    )
    assert dry_run.status_code == 200
    assert dry_run.json()["state_count"] == 2
    assert client.get(
        f"/api/learner-identities/{identity_id}/concept-states"
    ).json()["states"] == []

    rebuilt = client.post(
        f"/api/learner-identities/{identity_id}/memory/rebuild",
        json={"algorithm_version": "evidence-half-life-v1", "dry_run": False},
    )
    assert rebuilt.status_code == 200
    assert rebuilt.json()["state_count"] == 2
    state = next(
        item for item in rebuilt.json()["states"] if item["concept_id"] == evidence_id
    )
    assert state["concept_title"] == "Evidence validity"
    assert state["predicted_retention"] < state["observed_mastery"]

    growth = client.get(
        f"/api/learner-identities/{identity_id}/growth",
        params={"concept_id": evidence_id},
    )
    assert growth.status_code == 200
    assert len(growth.json()["series"][0]["points"]) == 2

    plan = client.post(
        f"/api/learner-identities/{identity_id}/retest-plans",
        json={"horizon_days": 90, "max_items": 2, "mode": "shadow"},
    )
    assert plan.status_code == 201
    assert plan.json()["status"] == "shadow"
    assert plan.json()["items"]
    assert plan.json()["items"][0]["reason_code"] == "unresolved_misconception"
    assert all(item["selected_question_id"] is None for item in plan.json()["items"])
    priorities = [item["priority"] for item in plan.json()["items"]]
    assert priorities == sorted(priorities, reverse=True)

    listed = client.get(
        f"/api/learner-identities/{identity_id}/retest-plans"
    ).json()
    assert len(listed["plans"]) == 1
    assert client.post(
        f"/api/learner-identities/{identity_id}/retest-plans",
        json={"mode": "active"},
    ).status_code == 422

    disabled = client.patch(
        f"/api/learner-identities/{identity_id}/memory-settings",
        json={"retest_planning_enabled": False},
    )
    assert disabled.status_code == 200
    blocked = client.post(
        f"/api/learner-identities/{identity_id}/retest-plans",
        json={"mode": "shadow"},
    )
    assert blocked.status_code == 409


def test_project_deletion_rebuilds_derived_state_and_removes_shadow_plans(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        identity, _, concept = _memory_fixture(db, now=now)
        project = Project(name="Disposable project")
        db.add(project)
        db.flush()
        subject = LearnerSubject(project_id=project.id, subject_key="temporary-subject")
        db.add(subject)
        db.flush()
        db.add(
            LearnerIdentityLink(
                learner_identity_id=identity.id,
                learner_subject_id=subject.id,
            )
        )
        for event in db.scalars(
            select(LearnerMemoryEvent).where(
                LearnerMemoryEvent.learner_identity_id == identity.id
            )
        ).all():
            event.learner_subject_id = subject.id
        service = LongitudinalStateService(db)
        service.rebuild(
            identity,
            algorithm_version="evidence-half-life-v1",
            dry_run=False,
            as_of=now,
        )
        service.create_retest_plan(
            identity,
            horizon_days=90,
            max_items=2,
            mode="shadow",
            as_of=now,
        )
        project_id = project.id
        identity_id = identity.id
        concept_id = concept.id
        db.commit()

    assert client.delete(f"/api/projects/{project_id}").status_code == 200
    with SessionLocal() as db:
        assert db.get(Concept, concept_id) is not None
        assert db.get(LearnerIdentity, identity_id) is not None
        assert db.scalar(select(func.count(LearnerConceptState.id))) == 0
        assert db.scalar(select(func.count(RetestPlan.id))) == 0
