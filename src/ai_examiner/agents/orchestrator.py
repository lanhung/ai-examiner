from __future__ import annotations

from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy.orm import Session

from ..config import get_settings
from ..model_catalog import estimate_cost
from ..models import Blueprint, ExamSession, Turn, UsageEvent
from ..providers.base import ModelProvider, ProviderResult
from ..services.budget import assert_budget
from ..services.cognitive import CognitiveStateService
from ..services.prompts import prompt_contents
from .adaptive import AdaptiveQuestionSelector, SelectionResult
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
        self.cognitive = CognitiveStateService(db)
        self.selector = AdaptiveQuestionSelector()
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
        self.cognitive.ensure_blueprint_graph(blueprint)
        selected = questions[0]
        selection = SelectionResult(selected, int(selected.get("difficulty", 2)), ["fixed_order"], [])
        if session.question_strategy == "adaptive":
            units, question_units = self.cognitive.graph(blueprint.id)
            selection = self.selector.select(
                questions=questions,
                question_units=question_units,
                states=self.cognitive.effective_states(session, units),
                units=units,
                asked_question_ids=[],
                prior_question_ids=self.cognitive.prior_question_ids(session),
            )
            selected = selection.question or questions[0]
        session.status = "active"
        session.state = "WAITING_FOR_ANSWER"
        session.started_at = utcnow()
        session.current_question_index = questions.index(selected)
        session.current_question_attempts = 0
        session.asked_question_ids = [selected["id"]]
        turn = Turn(
            session_id=session.id,
            role="assistant",
            kind="question",
            question_id=selected["id"],
            content=self.interviewer.opening(selected),
        )
        self.db.add(turn)
        self.db.flush()
        self.cognitive.record_decision(
            session=session,
            turn_id=turn.id,
            action="ASK_NEW",
            selected_question_id=selected["id"],
            target_difficulty=selection.target_difficulty,
            reason_codes=selection.reason_codes,
            candidate_scores=selection.candidate_scores,
            policy_config=self.selector.weights if session.question_strategy == "adaptive" else {},
        )
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
        analysis_question = self._analysis_question(session, question)
        history = [
            {"role": t.role, "content": t.content, "question_id": t.question_id}
            for t in session.turns[-6:]
        ]
        session.state = "ANALYZING"
        analysis = self.analyzer.analyze(
            question=analysis_question, answer=answer, history=history
        )
        analysis["active_question_text"] = str(analysis_question.get("text", ""))
        analysis["question_context"] = str(
            analysis_question.get("question_context", "main")
        )
        evaluation = self.evaluator.evaluate(
            question=analysis_question, answer=answer, analysis=analysis
        )
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
        self.db.flush()

        mastery = dict(session.mastery_state or {})
        mastery[question["id"]] = {
            "score": evaluation["score"],
            "confidence": evaluation["confidence"],
            "missing_points": evaluation["missing_points"],
        }
        session.mastery_state = mastery
        assistance_level = self._assistance_level(session)
        self.cognitive.record_answer(
            session=session,
            blueprint=blueprint,
            turn=user_turn,
            question=question,
            analysis=analysis,
            evaluation=evaluation,
            assistance_level=assistance_level,
        )
        asked_question_ids = list(session.asked_question_ids or [question["id"]])
        is_last = len(asked_question_ids) >= limit
        decision = self.policy.decide(
            analysis=analysis,
            attempts=session.current_question_attempts,
            question=question,
            config=session.config,
            is_last_question=is_last,
        )

        next_question = None
        selection: SelectionResult | None = None
        if decision["action"] in {"ASK_FOLLOWUP", "GIVE_HINT"}:
            session.current_question_attempts += 1
            session.state = "WAITING_FOR_ANSWER"
        elif decision["action"] == "MOVE_ON":
            if session.question_strategy == "adaptive":
                units, question_units = self.cognitive.graph(blueprint.id)
                selection = self.selector.select(
                    questions=questions,
                    question_units=question_units,
                    states=self.cognitive.effective_states(session, units),
                    units=units,
                    asked_question_ids=asked_question_ids,
                    current_question_id=question["id"],
                    prior_question_ids=self.cognitive.prior_question_ids(session),
                )
                next_question = selection.question
            else:
                next_index = index + 1
                if next_index < len(questions) and len(asked_question_ids) < limit:
                    next_question = questions[next_index]
                    selection = SelectionResult(
                        next_question,
                        int(next_question.get("difficulty", 3)),
                        ["fixed_order"],
                        [],
                    )
            if next_question:
                session.current_question_index = questions.index(next_question)
                session.current_question_attempts = 0
                session.state = "WAITING_FOR_ANSWER"
                asked_question_ids.append(next_question["id"])
                session.asked_question_ids = asked_question_ids
                decision["selection"] = {
                    "question_id": next_question["id"],
                    "target_difficulty": selection.target_difficulty if selection else None,
                    "reason_codes": selection.reason_codes if selection else [],
                }
            else:
                decision = {"action": "END", "reason": "no_eligible_question"}
                session.status = "completed"
                session.state = "COMPLETED"
                session.completed_at = utcnow()
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
        self.db.flush()
        self.cognitive.record_decision(
            session=session,
            turn_id=assistant_turn.id,
            action=decision["action"],
            selected_question_id=(next_question or question).get("id")
            if decision["action"] != "END"
            else None,
            target_difficulty=(selection.target_difficulty if selection else None),
            reason_codes=(selection.reason_codes if selection else [decision.get("reason", "policy")]),
            candidate_scores=(selection.candidate_scores if selection else []),
            policy_config=self.selector.weights if session.question_strategy == "adaptive" else {},
        )
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

    @staticmethod
    def _analysis_question(session: ExamSession, question: dict[str, Any]) -> dict[str, Any]:
        """Return the exact question the learner is currently answering."""
        if session.current_question_attempts <= 0:
            return question
        for turn in reversed(session.turns):
            if turn.role != "assistant":
                continue
            decision = (turn.analysis or {}).get("policy_decision", {})
            followup = decision.get("followup")
            if decision.get("action") == "ASK_FOLLOWUP" and followup:
                return {
                    **question,
                    "text": str(followup),
                    "expected_points": [],
                    "followups": [],
                    "question_context": "followup",
                    "parent_question": question.get("text", ""),
                    "parent_expected_points": list(question.get("expected_points") or []),
                }
            break
        return question

    def finalize_voice_transcripts(
        self, session: ExamSession, blueprint: Blueprint
    ) -> list[dict[str, Any]]:
        """Analyze final voice transcripts through the authoritative text pipeline."""
        questions = blueprint.data.get("questions", [])
        if not questions:
            return []
        transcript_turns = [turn for turn in session.turns if turn.kind == "voice_transcript"]
        finalized = []
        last_assistant_text = ""
        answer_index = 0
        asked = list(session.asked_question_ids or [])
        self.cognitive.ensure_blueprint_graph(blueprint)
        for position, turn in enumerate(transcript_turns):
            if turn.role == "assistant":
                last_assistant_text = turn.content
                continue
            if turn.role != "user" or not turn.content.strip():
                continue
            if (turn.analysis or {}).get("cognitive_finalized"):
                continue
            question = self._match_voice_question(last_assistant_text, questions, answer_index)
            answer_index += 1
            history = [
                {"role": item.role, "content": item.content, "question_id": item.question_id}
                for item in transcript_turns[max(0, position - 6) : position]
            ]
            analysis = self.analyzer.analyze(
                question=question, answer=turn.content, history=history
            )
            evaluation = self.evaluator.evaluate(
                question=question, answer=turn.content, analysis=analysis
            )
            turn.question_id = str(question["id"])
            turn.analysis = {
                **analysis,
                "cognitive_finalized": True,
                "source_type": "voice",
            }
            turn.evaluation = evaluation
            mastery = dict(session.mastery_state or {})
            mastery[str(question["id"])] = {
                "score": evaluation["score"],
                "confidence": evaluation["confidence"],
                "missing_points": evaluation["missing_points"],
            }
            session.mastery_state = mastery
            events = self.cognitive.record_answer(
                session=session,
                blueprint=blueprint,
                turn=turn,
                question=question,
                analysis=analysis,
                evaluation=evaluation,
                source_type="voice",
            )
            if question["id"] not in asked:
                asked.append(question["id"])
            self.cognitive.record_decision(
                session=session,
                turn_id=turn.id,
                action="VOICE_FINALIZED",
                selected_question_id=str(question["id"]),
                target_difficulty=int(question.get("difficulty", 3)),
                reason_codes=["final_transcript_evidence"],
                candidate_scores=[],
                policy_config=self.selector.weights,
            )
            finalized.append(
                {
                    "turn_id": turn.id,
                    "question_id": question["id"],
                    "evidence_event_ids": [event.id for event in events],
                }
            )
        session.asked_question_ids = asked
        self.db.commit()
        return finalized

    @staticmethod
    def _match_voice_question(
        assistant_text: str, questions: list[dict[str, Any]], answer_index: int
    ) -> dict[str, Any]:
        if assistant_text.strip():
            normalized = " ".join(assistant_text.lower().split())
            scored = [
                (
                    SequenceMatcher(
                        None,
                        normalized,
                        " ".join(str(question.get("text", "")).lower().split()),
                    ).ratio(),
                    question,
                )
                for question in questions
            ]
            score, candidate = max(scored, key=lambda item: item[0])
            if score >= 0.20:
                return candidate
        return questions[min(answer_index, len(questions) - 1)]

    @staticmethod
    def _assistance_level(session: ExamSession) -> str:
        if session.current_question_attempts <= 0:
            return "direct"
        for turn in reversed(session.turns):
            policy = (turn.analysis or {}).get("policy_decision", {})
            if policy.get("action") == "GIVE_HINT":
                return "hint"
            if policy.get("action") == "ASK_FOLLOWUP":
                return "followup"
        return "followup"
