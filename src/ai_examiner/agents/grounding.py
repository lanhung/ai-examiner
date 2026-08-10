from __future__ import annotations

import re


class GroundingChecker:
    name = "grounding_checker"

    @staticmethod
    def _normalized_text(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    def check_blueprint(self, blueprint: dict, document_text: str) -> dict:
        issues: list[str] = []
        normalized_document = self._normalized_text(document_text)
        for question in blueprint.get("questions", []):
            excerpt = (question.get("source_excerpt") or "").strip()
            normalized_excerpt = self._normalized_text(excerpt)
            if (
                normalized_excerpt
                and normalized_excerpt not in normalized_document
                and len(normalized_excerpt) > 80
            ):
                issues.append(
                    f"{question.get('id')}: source excerpt is not an exact document substring"
                )
        return {
            "passed": not issues,
            "issues": issues,
            "question_count": len(blueprint.get("questions", [])),
        }
