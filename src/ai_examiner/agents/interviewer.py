from __future__ import annotations

import zlib

FOLLOWUP_OPENERS = (
    "我继续追问一下：",
    "再深入一点：",
    "接着这个思路：",
    "我想再确认一下：",
)
MOVE_ON_ADEQUATE = (
    "好的，这道题的回答比较完整。",
    "明白了，这一题就到这里。",
    "谢谢，这部分讲清楚了。",
)
# Used when follow-ups are exhausted but the answer is still weak: never imply
# the answer was sufficient.
MOVE_ON_WEAK = (
    "这道题我们先到这里，提交后可以在报告里看到改进方向。",
    "这一题先告一段落，报告里会给出需要加强的地方。",
)
WEAK_COVERAGE = 0.72


def _pick(options: tuple[str, ...], *keys: object) -> str:
    seed = "|".join(str(key) for key in keys)
    return options[zlib.crc32(seed.encode("utf-8")) % len(options)]


def _answer_was_weak(analysis: dict) -> bool:
    try:
        coverage = float(analysis.get("coverage", 1.0))
    except (TypeError, ValueError):
        coverage = 1.0
    return (
        not analysis.get("answered", True)
        or bool(analysis.get("errors"))
        or coverage < WEAK_COVERAGE
    )


class Interviewer:
    name = "interviewer"

    def opening(self, question: dict) -> str:
        return f"我们开始。第一个问题：{question['text']}"

    def respond(
        self, *, decision: dict, analysis: dict, question: dict, next_question: dict | None
    ) -> str:
        action = decision["action"]
        question_id = question.get("id", "")
        if action == "GIVE_HINT":
            points = question.get("expected_points", [])
            hint = points[0] if points else "先界定问题，再说明依据"
            return f"先给一个方向性提示：可以从“{hint}”开始组织。请重新回答当前问题。"
        if action == "ASK_FOLLOWUP":
            followup = decision.get("followup")
            if not followup:
                missing = analysis.get("missing_points") or ["关键依据"]
                followup = f"请进一步说明：{missing[0]}。"
            return f"{_pick(FOLLOWUP_OPENERS, question_id, followup)}{followup}"
        if action == "MOVE_ON" and next_question:
            options = MOVE_ON_WEAK if _answer_was_weak(analysis) else MOVE_ON_ADEQUATE
            transition = _pick(options, question_id, next_question.get("id", ""))
            return f"{transition}下一个问题：{next_question['text']}"
        if action == "END":
            return "本轮到此结束，谢谢你的回答。系统正在汇总逐题表现、薄弱点和改进建议。"
        return "请继续。"
