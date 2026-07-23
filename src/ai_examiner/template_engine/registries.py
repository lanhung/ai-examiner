from __future__ import annotations

ALLOWED_ACTIONS = frozenset(
    {
        "ASK_FOLLOWUP",
        "ASK_FOR_REASON",
        "ASK_FOR_EVIDENCE",
        "ASK_FOR_EXAMPLE",
        "ASK_FOR_COUNTEREXAMPLE",
        "CHALLENGE",
        "CLARIFY",
        "GIVE_HINT",
        "CORRECT",
        "MOVE_ON",
        "ANSWER_USER",
        "END",
    }
)

QUESTION_TYPES = frozenset(
    {
        "recall",
        "explain",
        "apply",
        "analyze",
        "compare",
        "evaluate",
        "create",
        "evidence",
        "limitation",
        "counterexample",
        "transfer",
        "metacognitive",
        "motivation",
        "novelty",
        "method",
        "assumption",
        "generalization",
        "critical_reflection",
        "tradeoff",
        "risk",
        "decision",
        "discovery",
        "objection",
        "procedure",
    }
)

REPORT_SECTIONS = frozenset(
    {
        "summary",
        "objective_scores",
        "dimension_scores",
        "evidence",
        "strengths",
        "weaknesses",
        "knowledge_map",
        "learning_gain",
        "improvement_path",
        "recommended_actions",
        "retest_plan",
    }
)

DISCLAIMER_IDS = frozenset(
    {
        "practice_not_formal_decision",
        "advisory_human_review_required",
        "training_not_employment_decision",
        "training_not_medical_advice",
    }
)

CAPABILITIES = frozenset(
    {
        "documents",
        "evidence",
        "assessment",
        "voice",
        "adaptive_questions",
        "long_term_memory",
        "visual_analysis",
    }
)

ROLE_IDS = frozenset(
    {
        "academic_examiner",
        "grant_reviewer",
        "oral_instructor",
        "technical_interviewer",
        "product_trainer",
        "sales_customer",
        "project_facilitator",
    }
)

STYLE_IDS = frozenset(
    {
        "rigorous_supportive",
        "neutral_formal",
        "socratic",
        "concise_challenging",
        "coaching",
        "roleplay",
        "facilitative",
    }
)

OVERRIDE_TARGETS = {
    "question_limit": ("question_selection", "question_limit"),
    "max_followups_per_question": (
        "conversation",
        "max_followups_per_question",
    ),
    "difficulty_initial": ("question_selection", "difficulty", "initial"),
    "question_strategy": ("question_selection", "strategy"),
    "hints_allowed": ("conversation", "assistance", "hints", "allowed"),
    "corrections_allowed": ("conversation", "assistance", "corrections", "allowed"),
    "active_interruption": ("conversation", "interruption", "enabled"),
    "voice_provider": ("voice", "provider"),
}

OVERRIDE_VALUE_TYPES = {
    "question_limit": int,
    "max_followups_per_question": int,
    "difficulty_initial": int,
    "question_strategy": str,
    "hints_allowed": bool,
    "corrections_allowed": bool,
    "active_interruption": bool,
    "voice_provider": str,
}

PLATFORM_PROHIBITED_USES = frozenset(
    {
        "automatic_admission_decision",
        "automatic_employment_decision",
        "automatic_medical_diagnosis",
        "protected_trait_inference",
        "personality_or_emotion_scoring",
    }
)
