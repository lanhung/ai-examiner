from __future__ import annotations

import re
from collections import Counter
from copy import deepcopy
from typing import Any

from .base import ModelProvider, ProviderResult

STOPWORDS = {
    "the",
    "and",
    "that",
    "this",
    "with",
    "from",
    "have",
    "were",
    "their",
    "which",
    "我们",
    "本文",
    "研究",
    "方法",
    "结果",
    "以及",
    "进行",
    "一个",
    "通过",
    "可以",
    "主要",
}


class MockProvider(ModelProvider):
    """Deterministic zero-cost provider for demos, tests, and offline evaluation."""

    name = "mock"
    model = "heuristic-v2"

    @staticmethod
    def _keywords(text: str, limit: int = 8) -> list[str]:
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}|[\u4e00-\u9fff]{2,6}", text.lower())
        counts = Counter(t for t in tokens if t not in STOPWORDS)
        return [word for word, _ in counts.most_common(limit)] or ["核心问题", "方法", "实验"]

    @staticmethod
    def _excerpt(text: str, limit: int = 360) -> str:
        compact = re.sub(r"\s+", " ", text).strip()
        return compact[:limit] or "演示材料未包含可解析文本。"

    def _planner(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("document_text", ""))
        keywords = self._keywords(text)
        excerpt = self._excerpt(text)
        questions = [
            {
                "id": "Q1",
                "text": "请用两分钟说明这项工作的核心科学问题，以及为什么值得研究。",
                "type": "motivation",
                "difficulty": 2,
                "expected_points": ["明确问题", "说明重要性", "界定研究范围"],
                "source_excerpt": excerpt,
                "source_page": 1,
                "followups": ["现有方法为什么不能充分解决它？", "这个问题的实际影响是什么？"],
            },
            {
                "id": "Q2",
                "text": f"围绕“{keywords[0]}”，您的方法与最接近的已有方法相比，真正新增了什么？",
                "type": "novelty",
                "difficulty": 3,
                "expected_points": ["明确比较对象", "指出实质差异", "避免仅陈述性能提升"],
                "source_excerpt": excerpt,
                "source_page": 1,
                "followups": ["如果去掉这一设计，结果会怎样？", "差异是否有消融实验支持？"],
            },
            {
                "id": "Q3",
                "text": "请列出该方法成立所依赖的两个关键假设，并说明假设失效时会发生什么。",
                "type": "assumption",
                "difficulty": 4,
                "expected_points": ["识别假设", "解释必要性", "讨论失效后果"],
                "source_excerpt": excerpt,
                "source_page": 1,
                "followups": ["哪个假设最脆弱？", "实验中如何验证该假设？"],
            },
            {
                "id": "Q4",
                "text": "为什么当前实验设计足以支持主要结论？请同时说明它不能支持什么。",
                "type": "evidence",
                "difficulty": 4,
                "expected_points": ["实验与结论对应", "基线合理", "承认证据边界"],
                "source_excerpt": excerpt,
                "source_page": 1,
                "followups": ["是否存在替代解释？", "最需要补充的实验是什么？"],
            },
            {
                "id": "Q5",
                "text": f"假设数据分布、尺度或条件发生明显变化，涉及“{keywords[1]}”的结论还能成立吗？",
                "type": "generalization",
                "difficulty": 5,
                "expected_points": ["区分内插外推", "说明适用域", "提出验证方案"],
                "source_excerpt": excerpt,
                "source_page": 1,
                "followups": ["最可能首先失效的部分是什么？", "如何设计分布外测试？"],
            },
            {
                "id": "Q6",
                "text": "作为最严格的审稿人，您认为这项工作最可能被拒稿的理由是什么？如何补强？",
                "type": "limitation",
                "difficulty": 5,
                "expected_points": ["识别核心短板", "给出可执行补强", "区分致命与次要问题"],
                "source_excerpt": excerpt,
                "source_page": 1,
                "followups": ["哪个补强最优先？", "如果无法新增实验，如何收缩论断？"],
            },
        ]
        scenario = payload.get("scenario_planning_contract") or {}
        allowed_types = list(scenario.get("allowed_question_types") or [])
        difficulty = scenario.get("difficulty") or {}
        minimum_difficulty = int(difficulty.get("minimum", 1))
        maximum_difficulty = int(difficulty.get("maximum", 5))
        if allowed_types:
            for index, question in enumerate(questions):
                question["type"] = allowed_types[index % len(allowed_types)]
                question["difficulty"] = min(
                    maximum_difficulty,
                    max(minimum_difficulty, int(question["difficulty"])),
                )
        return {
            "title": payload.get("filename", "未命名材料"),
            "summary": (
                f"该材料主要围绕 {', '.join(keywords[:4])} 展开。演示模式使用启发式分析；"
                "配置真实模型后会生成材料专属蓝图。"
            ),
            "core_contributions": [
                f"围绕 {key} 的潜在贡献，需要在答辩中进一步验证" for key in keywords[:3]
            ],
            "assumptions": [
                "数据与实验设置能够代表目标场景",
                "比较基线与评价指标足以支撑主要论断",
            ],
            "risks": ["贡献可能描述得过宽", "证据边界和泛化范围可能未充分说明"],
            "questions": questions,
        }

    def _golden_cases(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("document_text", ""))
        count = int(payload.get("requested_question_count", 8))
        plan = self._planner(payload)
        base_questions = plan["questions"]
        excerpt = self._excerpt(text)
        keywords = self._keywords(text, 10)
        extra = [
            {
                "text": f"请逐步解释涉及“{keywords[2]}”的核心方法链条，并指出最容易出错的环节。",
                "type": "method",
                "difficulty": 4,
                "expected_points": ["方法步骤", "输入输出", "失效环节"],
                "followups": ["哪一步最依赖经验参数？", "如何用消融验证该步骤？"],
            },
            {
                "text": "论文中的主要结论与所展示证据之间是否存在过度外推？请给出边界。",
                "type": "evidence",
                "difficulty": 5,
                "expected_points": ["对应具体结论", "对应具体证据", "说明不可推断部分"],
                "followups": ["哪一句论断最需要收缩？", "什么新增证据可解除这一限制？"],
            },
            {
                "text": "如果必须删除一项实验，删除哪一项对主结论伤害最小？为什么？",
                "type": "critical_reflection",
                "difficulty": 4,
                "expected_points": ["识别证据层级", "解释冗余性", "保护核心因果链"],
                "followups": ["反过来，哪项实验绝不能删除？"],
            },
            {
                "text": "请提出一个最有可能推翻论文主要结论的反事实测试，并说明判定标准。",
                "type": "generalization",
                "difficulty": 5,
                "expected_points": ["明确反事实条件", "给出可执行测试", "定义失败标准"],
                "followups": ["该测试为何比简单增加数据更有信息量？"],
            },
        ]
        expanded = base_questions + extra
        cases: list[dict[str, Any]] = []
        for index, question in enumerate(expanded[:count], start=1):
            required = list(question.get("expected_points", []))
            ideal = "；".join(required) + "，并将这些要点与论文中的具体材料和证据对应起来。"
            cases.append(
                {
                    "id": f"Q{index}",
                    "question": question["text"],
                    "type": question["type"],
                    "difficulty": question["difficulty"],
                    "rationale": "该问题用于区分对论文的表面复述与对论证链条的真实理解。",
                    "ideal_answer": ideal,
                    "required_points": required,
                    "followups": question.get("followups", [])[:2] or ["请给出论文中的具体证据。"],
                    "common_errors": [
                        "只重复论文结论，没有解释理由",
                        "把相关性证据误当作因果证据",
                    ],
                    "scoring_rubric": {
                        "excellent": "覆盖全部要点，引用材料证据，并明确结论边界。",
                        "acceptable": "覆盖多数要点，但证据、边界或反思仍不充分。",
                        "insufficient": "回避核心问题，或仅给出无证据的笼统判断。",
                    },
                    "source_excerpt": excerpt,
                    "source_page": 1,
                    "confidence": 0.72,
                }
            )
        return {
            "paper_title": payload.get("filename", "未命名材料"),
            "scope_summary": plan["summary"],
            "cases": cases,
        }

    @staticmethod
    def _critic(payload: dict[str, Any]) -> dict[str, Any]:
        candidate = payload.get("candidate") or {}
        reviews = []
        for case in candidate.get("cases") or []:
            reviews.append(
                {
                    "case_id": case.get("id", "?"),
                    "groundedness": 4,
                    "relevance": 4,
                    "clarity": 4,
                    "discrimination": 4,
                    "answerability": 4,
                    "accept": True,
                    "fatal_issues": [],
                    "suggested_revision": "真实模型模式下应进一步核对页码与材料专属性。",
                }
            )
        return {"reviews": reviews, "dataset_issues": ["演示模式问题具有模板化倾向"]}

    @staticmethod
    def _consensus(payload: dict[str, Any]) -> dict[str, Any]:
        candidates = payload.get("candidates") or []
        count = int(payload.get("requested_question_count", 8))
        selected = deepcopy((candidates[0] if candidates else {}).get("cases") or [])[:count]
        profiles = [c.get("generator_profile", "mock:heuristic-v2") for c in candidates]
        for index, case in enumerate(selected, start=1):
            case["id"] = f"Q{index}"
            case["consensus_reason"] = "候选问题通过交叉审查，且覆盖独立的答辩能力维度。"
            case["source_models"] = profiles or ["mock:heuristic-v2"]
            case["quality_scores"] = {
                "groundedness": 4,
                "relevance": 4,
                "clarity": 4,
                "discrimination": 4,
                "answerability": 4,
            }
        first = candidates[0] if candidates else {}
        return {
            "paper_title": first.get("paper_title", "未命名材料"),
            "scope_summary": first.get("scope_summary", ""),
            "cases": selected,
            "excluded_case_reasons": [],
        }

    @staticmethod
    def _synthetic_answers(payload: dict[str, Any]) -> dict[str, Any]:
        answers = []
        for case in payload.get("cases") or []:
            points = case.get("required_points") or ["核心要点"]
            excellent = "。".join(points) + "。这些要点共同限定了结论及其证据边界。"
            partial = f"我认为关键在于{points[0]}，但其他条件和证据还需要进一步说明。"
            answers.append(
                {
                    "case_id": case.get("id", "?"),
                    "variants": [
                        {
                            "variant": "excellent",
                            "answer": excellent,
                            "expected_correctness": "supported",
                            "expected_coverage": 0.95,
                            "expected_errors": [],
                            "generation_notes": "覆盖全部规定要点。",
                        },
                        {
                            "variant": "partial",
                            "answer": partial,
                            "expected_correctness": "partially_supported",
                            "expected_coverage": 0.45,
                            "expected_errors": ["遗漏部分必要要点"],
                            "generation_notes": "有相关内容但覆盖不足。",
                        },
                        {
                            "variant": "misconception",
                            "answer": "只要实验指标提高，就能够证明该方法在所有条件下都具有因果优势。",
                            "expected_correctness": "unsupported",
                            "expected_coverage": 0.2,
                            "expected_errors": ["把性能相关性误当作普遍因果结论"],
                            "generation_notes": "流畅但包含明确概念错误。",
                        },
                        {
                            "variant": "evasive",
                            "answer": "这是一个很重要的问题，我们做了大量工作，整体结果也非常令人鼓舞。",
                            "expected_correctness": "insufficient",
                            "expected_coverage": 0.05,
                            "expected_errors": ["没有回答问题"],
                            "generation_notes": "语句流畅但回避核心。",
                        },
                    ],
                }
            )
        return {"answers": answers}

    @staticmethod
    def _answer_analyzer(payload: dict[str, Any]) -> dict[str, Any]:
        answer = str(payload.get("answer", "")).strip()
        question = payload.get("question", {})
        expected = question.get("expected_points", [])
        point_records = list(question.get("expected_point_records") or [])
        lower = answer.lower()
        weak = len(answer) < 35 or any(x in lower for x in ["不知道", "不清楚", "no idea"])
        evasive = any(x in lower for x in ["很重要的问题", "大量工作", "令人鼓舞"])
        misconception = any(x in lower for x in ["所有条件", "因果优势", "一定证明"])
        evidence_terms = [
            "因为",
            "例如",
            "实验",
            "数据",
            "基线",
            "原因",
            "证据",
            "because",
            "for example",
        ]
        evidence = any(term in lower for term in evidence_terms)
        coverage = min(1.0, max(0.05, len(answer) / 220))
        if evidence:
            coverage = min(1.0, coverage + 0.2)
        if evasive:
            coverage = 0.05
        if misconception:
            coverage = min(coverage, 0.2)
        if weak or evasive:
            correctness = "insufficient"
        elif misconception:
            correctness = "unsupported"
        elif not evidence:
            correctness = "partially_supported"
        else:
            correctness = "supported"
        errors: list[str] = []
        if weak or evasive:
            errors.append("回答信息不足，尚不能支持结论")
        if misconception:
            errors.append("把局部性能证据错误外推为普遍因果结论")
        target = coverage * max(1, len(point_records))
        full_points = int(target)
        partial_point = target - full_points >= 0.25
        point_assessments = []
        for index, point in enumerate(point_records):
            if misconception and index == 0:
                status = "contradicted"
            elif index < full_points:
                status = "covered"
            elif index == full_points and partial_point:
                status = "partial"
            else:
                status = "missing"
            point_assessments.append(
                {
                    "point_id": point.get("id", f"P{index + 1}"),
                    "status": status,
                    "answer_quote": answer[:180] if status in {"covered", "partial"} else "",
                    "source_evidence_id": "mock-source" if evidence else "",
                    "reason": "Deterministic mock point assessment.",
                }
            )
        return {
            "answered": not weak and not evasive,
            "correctness": correctness,
            "claims": [answer[:180]] if answer else [],
            "errors": errors,
            "missing_points": expected[1:] if coverage < 0.65 else [],
            "point_assessments": point_assessments,
            "source_grounding": 0.9 if evidence else 0.2,
            "reasoning_quality": 0.85 if evidence else 0.3,
            "boundary_awareness": 0.75 if any(
                term in lower for term in ["but", "limited", "however"]
            ) else 0.4,
            "confidence": 0.68,
            "followup_candidates": question.get("followups", []),
        }

    def complete_json(
        self,
        *,
        agent: str,
        instructions: str,
        payload: dict[str, Any],
        schema_hint: dict[str, Any],
    ) -> ProviderResult:
        del instructions, schema_hint
        if agent == "session_planner":
            data = self._planner(payload)
        elif agent == "answer_analyzer":
            data = self._answer_analyzer(payload)
        elif agent == "golden_annotator":
            data = self._golden_cases(payload)
        elif agent == "annotation_critic":
            data = self._critic(payload)
        elif agent == "consensus_synthesizer":
            data = self._consensus(payload)
        elif agent == "synthetic_answer_generator":
            data = self._synthetic_answers(payload)
        elif agent == "visual_evidence":
            page = int(payload.get("page_number", 1))
            data = {
                "page_number": page,
                "visual_type": "page",
                "summary": "演示模式基于提取文本生成页面级视觉审查摘要。",
                "observations": ["页面包含可用于答辩追问的文本或视觉证据。"],
                "claims_supported": ["页面内容可支持局部材料描述。"],
                "claims_not_supported": ["仅凭单页不能证明跨场景泛化或因果关系。"],
                "potential_issues": ["应检查图表标签、比较基线和证据边界。"],
                "exam_questions": [
                    {
                        "question": f"请解释第 {page} 页证据真正支持了什么，以及不能支持什么。",
                        "rationale": "检查作者是否区分观察结果与外推结论。",
                        "difficulty": 4,
                        "expected_points": ["证据内容", "结论边界", "替代解释"],
                    }
                ],
                "confidence": 0.62,
            }
        elif agent == "joint_analysis":
            documents = payload.get("documents") or []
            ids = [str(item.get("document_id", "")) for item in documents]
            data = {
                "package_summary": f"共比较 {len(documents)} 份材料。",
                "alignments": ["主要材料围绕同一研究主题展开。"],
                "contradictions": [],
                "omissions": ["演示模式无法可靠验证所有图表与论断对应关系。"],
                "unsupported_claims": [],
                "presentation_gaps": ["建议核对论文与汇报中的贡献表述是否一致。"],
                "high_risk_questions": [
                    {
                        "question": "论文与汇报材料中最核心的结论是否使用了相同证据边界？",
                        "rationale": "检查跨文档一致性。",
                        "document_ids": ids,
                        "evidence": ["各文档摘要与主要结论"],
                    }
                ],
                "recommended_actions": ["逐项对齐论文结论、PPT 页面和支撑证据。"],
                "confidence": 0.6,
            }
        else:
            data = {"ok": True, "agent": agent}
        return ProviderResult(data=data, provider=self.name, model=self.model)

    def complete_text(
        self, *, agent: str, instructions: str, payload: dict[str, Any]
    ) -> ProviderResult:
        del instructions
        return ProviderResult(
            data=f"[{agent}] {payload.get('prompt', '演示模式响应')}",
            provider=self.name,
            model=self.model,
        )
