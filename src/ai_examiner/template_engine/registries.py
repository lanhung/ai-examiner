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
