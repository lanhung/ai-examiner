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

ASSESSMENT_DIMENSIONS = {
    "correctness": {
        "components": {"correctness": 1.0},
        "anchors": {
            "excellent": {
                "zh-CN": "结论正确，并与问题及材料证据一致。",
                "en": "Claims are correct and aligned with the question and source evidence.",
            },
            "acceptable": {
                "zh-CN": "主要结论基本正确，但存在轻微偏差或限定不足。",
                "en": "The main claims are mostly correct with minor gaps or missing qualifications.",
            },
            "insufficient": {
                "zh-CN": "结论错误、缺少支持，或没有回答当前问题。",
                "en": "Claims are incorrect, unsupported, or do not answer the active question.",
            },
        },
    },
    "completeness": {
        "components": {"coverage": 1.0},
        "anchors": {
            "excellent": {
                "zh-CN": "覆盖全部关键回答点，没有重要遗漏。",
                "en": "Covers all required answer points without material omissions.",
            },
            "acceptable": {
                "zh-CN": "覆盖主要回答点，但仍遗漏部分重要内容。",
                "en": "Covers the main answer points but omits some important content.",
            },
            "insufficient": {
                "zh-CN": "仅覆盖少量回答点，或回答明显不完整。",
                "en": "Covers few required points or is materially incomplete.",
            },
        },
    },
    "evidence_reasoning": {
        "components": {"source_grounding": 0.5, "reasoning_quality": 0.5},
        "anchors": {
            "excellent": {
                "zh-CN": "使用可追溯证据，并清楚解释证据如何支持结论。",
                "en": "Uses traceable evidence and clearly explains how it supports the claims.",
            },
            "acceptable": {
                "zh-CN": "提供部分证据或推理，但证据与结论的连接不够完整。",
                "en": "Provides some evidence or reasoning, but the connection to claims is incomplete.",
            },
            "insufficient": {
                "zh-CN": "缺少可核查证据，或仅给出未经解释的结论。",
                "en": "Lacks verifiable evidence or gives conclusions without reasoning.",
            },
        },
    },
    "boundary_awareness": {
        "components": {"boundary_awareness": 1.0},
        "anchors": {
            "excellent": {
                "zh-CN": "明确说明假设、适用条件、不确定性和结论边界。",
                "en": "States assumptions, applicability, uncertainty, and claim boundaries.",
            },
            "acceptable": {
                "zh-CN": "意识到部分边界，但未完整说明其影响。",
                "en": "Recognizes some boundaries but does not fully explain their impact.",
            },
            "insufficient": {
                "zh-CN": "过度外推结论，或忽略关键假设与限制。",
                "en": "Overgeneralizes claims or ignores material assumptions and limitations.",
            },
        },
    },
}

DISCLAIMER_TEXTS = {
    "practice_not_formal_decision": {
        "zh-CN": "本报告仅用于训练和辅助判断，不应作为正式学位、录取、招聘或人事决定的唯一依据。",
        "en": (
            "This report is for practice and advisory use only and must not be the sole "
            "basis for degree, admission, employment, or personnel decisions."
        ),
    },
    "advisory_human_review_required": {
        "zh-CN": "本报告仅提供辅助意见，任何高影响决定都必须经过有资格的人类复核。",
        "en": (
            "This report is advisory. Any high-impact decision requires review by a "
            "qualified human."
        ),
    },
    "training_not_employment_decision": {
        "zh-CN": "本报告仅用于训练，不得用于自动作出招聘、晋升或解雇决定。",
        "en": (
            "This report is for training only and must not be used to make automated "
            "hiring, promotion, or termination decisions."
        ),
    },
    "training_not_medical_advice": {
        "zh-CN": "本报告仅用于训练，不构成医疗建议、诊断或治疗决定。",
        "en": "This report is for training only and is not medical advice, diagnosis, or treatment.",
    },
}

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

ROLE_BEHAVIOR_GUIDANCE = {
    "academic_examiner": (
        "Test research contribution, methodological validity, evidence strength, "
        "assumptions, limitations, and defensibility. Frame questions as a thesis "
        "committee member and require claims to be bounded by the supplied evidence."
    ),
    "grant_reviewer": (
        "Test significance, feasibility, research design, risk mitigation, and value "
        "for resources. Frame questions as funding-review decisions without promising "
        "an award or making an automated funding decision."
    ),
    "oral_instructor": (
        "Diagnose course learning rather than research novelty. Ask the learner to "
        "explain concepts in their own words, apply them to a new case, correct a "
        "misconception, or reflect on transfer. Use a teaching progression and make "
        "the follow-up help reveal the learner's reasoning."
    ),
    "technical_interviewer": (
        "Evaluate engineering judgment under explicit requirements and constraints. "
        "Ask for architecture choices, tradeoffs, failure modes, validation methods, "
        "and decision rationale. Be concise and challenging; do not turn the question "
        "into an academic defense or give away the solution."
    ),
    "product_trainer": (
        "Evaluate accurate product explanation, customer fit, supported use cases, "
        "operational procedure, and capability boundaries. Challenge unsupported "
        "claims and make the follow-up test how the learner would explain or apply "
        "the product safely with a customer."
    ),
    "sales_customer": (
        "Role-play a realistic customer with a concrete objection, constraint, and "
        "decision concern. Test discovery, evidence-based response, boundary honesty, "
        "and next-step handling rather than academic recall."
    ),
    "project_facilitator": (
        "Facilitate a project review that turns evidence into exactly one concrete "
        "decision or commitment. Every initial question must require one of: a named "
        "owner, deadline, measurable trigger, rollback criterion, corrective action, "
        "or observable process change. Do not stop at classifying facts, explaining "
        "evidence, or asking whether a conclusion is supported."
    ),
}

STYLE_BEHAVIOR_GUIDANCE = {
    "rigorous_supportive": (
        "Use precise, demanding questions while remaining constructive."
    ),
    "neutral_formal": "Use neutral, formal, decision-relevant language.",
    "socratic": (
        "Use one focused question that prompts explanation or reflection before "
        "providing help."
    ),
    "concise_challenging": (
        "Use compact wording, explicit constraints, and a probing challenge."
    ),
    "coaching": (
        "Use practical, corrective language and identify an actionable improvement."
    ),
    "roleplay": (
        "Stay inside the assigned stakeholder role and react naturally to the answer."
    ),
    "facilitative": (
        "Clarify ownership and evidence, then move toward a concrete next action."
    ),
}


def presentation_behavior(presentation: dict[str, str]) -> dict[str, str]:
    role_id = str(presentation.get("role_id") or "")
    style_id = str(presentation.get("style_id") or "")
    return {
        "role_id": role_id,
        "style_id": style_id,
        "role_behavior": ROLE_BEHAVIOR_GUIDANCE.get(role_id, ""),
        "style_behavior": STYLE_BEHAVIOR_GUIDANCE.get(style_id, ""),
    }

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
