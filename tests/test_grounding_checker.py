from ai_examiner.agents.grounding import GroundingChecker


def _blueprint(excerpt: str) -> dict:
    return {
        "questions": [
            {
                "id": "Q1",
                "source_excerpt": excerpt,
            }
        ]
    }


def test_grounding_accepts_exact_evidence_with_layout_whitespace_changes():
    document = (
        "The main limitation is\n"
        "that the current study uses one domain and cannot establish "
        "cross-domain generalization."
    )
    excerpt = (
        "The main limitation is that the current study uses one domain and "
        "cannot establish cross-domain generalization."
    )

    result = GroundingChecker().check_blueprint(_blueprint(excerpt), document)

    assert result["passed"] is True
    assert result["issues"] == []


def test_grounding_still_rejects_long_paraphrased_evidence():
    document = "The paper reports one experiment and explicitly limits its claim."
    excerpt = (
        "The paper reports a comprehensive multi-domain experiment that proves "
        "the method generalizes reliably to every unseen distribution and setting."
    )

    result = GroundingChecker().check_blueprint(_blueprint(excerpt), document)

    assert result["passed"] is False
    assert result["issues"] == [
        "Q1: source excerpt is not an exact document substring"
    ]
