from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..config import get_settings
from ..model_catalog import estimate_cost
from ..models import Blueprint, ExamSession, Turn, UsageEvent
from ..providers.base import ModelProvider, ProviderResult
from ..services.budget import assert_budget
from ..services.prompts import prompt_contents
from .analyzer import AnswerAnalyzer
from .base import AgentContext
from .evaluator import Evaluator
from .grounding import GroundingChecker
from .interviewer import Interviewer
from .planner import SessionPlanner
from .policy import PolicyController
from .reporter import ReportGenerator


def utcnow() -> datetime:
    return datetime.now(UTC)


class ExamOrchestrator:
    def __init__(
        self,
        db: Session,
        provider: ModelProvider,
        project_id: str | None = None,
        session_id: str | None = None,
    ):
        self.db = db
        self.project_id = project_id
        self.session_id = session_id
        context = AgentContext(
            provider=provider,
            record_usage=self._record_usage,
            prompt_overrides=prompt_contents(db),
        )
        self.planner = SessionPlanner(context)
        self.analyzer = AnswerAnalyzer(context)
        self.policy = PolicyController()
        self.evaluator = Evaluator()
        self.interviewer = Interviewer()
        self.grounding = GroundingChecker()
        self.reporter = ReportGenerator()
        self.provider = provider

    def _record_usage(self, agent: str, result: ProviderResult) -> None:
        assert_budget(self.db, get_settings(), self.project_id)
        self.db.add(
            UsageEvent(
                project_id=self.project_id,
                session_id=self.session_id,
                agent=agent,
                provider=result.provider,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                estimated_cost_usd=estimate_cost(
                    result.provider, result.model, result.input_tokens, result.output_tokens
                ),
            )
        )

    def build_blueprint(
        self, *, document_text: str, filename: str, language: str
    ) -> tuple[dict, dict]:
        blueprint = self.planner.plan(
            document_text=document_text, filename=filename, language=language
        )
        grounding = self.grounding.check_blueprint(blueprint, document_text)
        blueprint["grounding_check"] = grounding
        return blueprint, grounding

    @staticmethod
    def _question_limit(session: ExamSession, blueprint: dict) -> int:
        return min(
            int(session.config.get("question_limit", 6)), len(blueprint.get("questions", []))
        )

    def start_session(self, session: ExamSession, blueprint: Blueprint) -> Turn:
        if session.status not in {"created", "ready"}:
            raise ValueError("Session has already started")
        questions = blueprint.data.get("questions", [])
        if not questions:
            raise ValueError("Blueprint contains no questions")
        session.status = "active"
        session.state = "WAITING_FOR_ANSWER"
        session.started_at = utcnow()
        session.current_question_index = 0
        session.current_question_attempts = 0
        turn = Turn(
            session_id=session.id,
            role="assistant",
            kind="question",
            question_id=questions[0]["id"],
            content=self.interviewer.opening(questions[0]),
        )
        self.db.add(turn)
        self.db.commit()
        self.db.refresh(turn)
        return turn

    def submit_answer(
        self, session: ExamSession, blueprint: Blueprint, answer: str
    ) -> dict[str, Any]:
        if session.status != "active":
            raise ValueError("Session is not active")
        questions = blueprint.data["questions"]
        limit = self._question_limit(session, blueprint.data)
        index = session.current_question_index
        question = questions[index]
        history = [
            {"role": t.role, "content": t.content, "question_id": t.question_id}
            for t in session.turns[-6:]
        ]
        session.state = "ANALYZING"
        analysis = self.analyzer.analyze(question=question, answer=answer, history=history)
        evaluation = self.evaluator.evaluate(question=question, answer=answer, analysis=analysis)
        user_turn = Turn(
            session_id=session.id,
            role="user",
            kind="answer",
            question_id=question["id"],
            content=answer,
            analysis=analysis,
            evaluation=evaluation,
        )
        self.db.add(user_turn)

        mastery = dict(session.mastery_state or {})
        mastery[question["id"]] = {
            "score": evaluation["score"],
            "confidence": evaluation["confidence"],
            "missing_points": evaluation["missing_points"],
        }
        session.mastery_state = mastery
        is_last = index >= limit - 1
        decision = self.policy.decide(
            analysis=analysis,
            attempts=session.current_question_attempts,
            question=question,
            config=session.config,
            is_last_question=is_last,
        )

        next_question = None
        if decision["action"] in {"ASK_FOLLOWUP", "GIVE_HINT"}:
            session.current_question_attempts += 1
            session.state = "WAITING_FOR_ANSWER"
        elif decision["action"] == "MOVE_ON":
            session.current_question_index += 1
            session.current_question_attempts = 0
            session.state = "WAITING_FOR_ANSWER"
            next_question = questions[session.current_question_index]
        elif decision["action"] == "END":
            session.status = "completed"
            session.state = "COMPLETED"
            session.completed_at = utcnow()

        assistant_text = self.interviewer.respond(
            decision=decision,
            analysis=analysis,
            question=question,
            next_question=next_question,
        )
        assistant_turn = Turn(
            session_id=session.id,
            role="assistant",
            kind="question" if decision["action"] != "END" else "closing",
            question_id=(next_question or question).get("id"),
            content=assistant_text,
            analysis={"policy_decision": decision},
        )
        self.db.add(assistant_turn)
        self.db.commit()
        self.db.refresh(user_turn)
        self.db.refresh(assistant_turn)
        return {
            "user_turn": user_turn,
            "assistant_turn": assistant_turn,
            "analysis": analysis,
            "evaluation": evaluation,
            "decision": decision,
            "completed": session.status == "completed",
        }
