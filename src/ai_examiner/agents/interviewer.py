from __future__ import annotations


class Interviewer:
    name = "interviewer"

    def opening(self, question: dict) -> str:
        return f"我们开始。第一个问题：{question['text']}"

    def respond(
        self, *, decision: dict, analysis: dict, question: dict, next_question: dict | None
    ) -> str:
        action = decision["action"]
        if action == "GIVE_HINT":
            points = question.get("expected_points", [])
            hint = points[0] if points else "先界定问题，再说明依据"
            return f"先给一个方向性提示：可以从“{hint}”开始组织。请重新回答当前问题。"
        if action == "ASK_FOLLOWUP":
            followup = decision.get("followup")
            if not followup:
                missing = analysis.get("missing_points") or ["关键依据"]
                followup = f"请进一步说明：{missing[0]}。"
            return f"我继续追问一下：{followup}"
        if action == "MOVE_ON" and next_question:
            return f"好的，现有回答已经提供了基本判断依据。下一个问题：{next_question['text']}"
        if action == "END":
            return "本轮答辩到此结束。系统正在汇总逐题证据、薄弱点和改进建议。"
        return "请继续。"
