from __future__ import annotations

import re
import unicodedata


class GroundingChecker:
    name = "grounding_checker"

    @staticmethod
    def _normalized_text(value: str) -> str:
        value = unicodedata.normalize("NFKC", value).replace("\u00ad", "")
        value = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", value)
        return re.sub(r"\s+", " ", value).strip()

    def check_blueprint(self, blueprint: dict, document_text: str, page_map: list[dict] | None = None) -> dict:
        issues: list[str] = []
        normalized_document = self._normalized_text(document_text)
        pages = {str(page["page"]): page for page in page_map or []}
        # Older page offsets excluded join separators. Use parser headers when
        # available, not those inaccurate offsets or the 2,000-character preview.
        sections = re.split(r"--- (?:PAGE|SLIDE) (\d+) ---", document_text)
        page_texts = dict(zip(sections[1::2], sections[2::2], strict=True))
        for question in blueprint.get("questions", []):
            excerpt = (question.get("source_excerpt") or "").strip()
            normalized_excerpt = self._normalized_text(excerpt)
            if not normalized_excerpt:
                issues.append(f"{question.get('id')}: source excerpt is required")
            elif normalized_excerpt not in normalized_document:
                issues.append(
                    f"{question.get('id')}: source excerpt is not an exact document substring"
                )
            if page_map is not None:
                page = str(question.get("source_page", ""))
                if page not in pages:
                    issues.append(f"{question.get('id')}: source page is missing or invalid")
                elif normalized_excerpt:
                    source = page_texts.get(page)
                    if source is None and len(pages) == 1:
                        source = document_text
                    if source is None:
                        issues.append(f"{question.get('id')}: source page text cannot be verified")
                    elif normalized_excerpt not in self._normalized_text(source):
                        issues.append(f"{question.get('id')}: source excerpt does not match the cited page")
        return {
            "passed": not issues,
            "issues": issues,
            "question_count": len(blueprint.get("questions", [])),
        }
