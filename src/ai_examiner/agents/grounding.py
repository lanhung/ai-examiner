from __future__ import annotations


class GroundingChecker:
    name = "grounding_checker"

    def check_blueprint(self, blueprint: dict, document_text: str) -> dict:
        issues: list[str] = []
        for question in blueprint.get("questions", []):
            excerpt = (question.get("source_excerpt") or "").strip()
            if excerpt and excerpt not in document_text and len(excerpt) > 80:
                issues.append(
                    f"{question.get('id')}: source excerpt is not an exact document substring"
                )
        return {
            "passed": not issues,
            "issues": issues,
            "question_count": len(blueprint.get("questions", [])),
        }
