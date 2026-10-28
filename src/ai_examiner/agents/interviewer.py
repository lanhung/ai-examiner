from __future__ import annotations


class Interviewer:
    name = "interviewer"

    def opening(self, question: dict, *, language: str = "zh-CN") -> str:
        prefix = "我们开始。第一个问题：" if language.lower().startswith("zh") else "Let's begin. First question: "
        return f"{prefix}{question['text']}"

    def respond(
        self, *, decision: dict, analysis: dict, question: dict, next_question: dict | None,
        language: str = "zh-CN",
    ) -> str:
        action = decision["action"]
        chinese = language.lower().startswith("zh")
        if action == "GIVE_HINT":
            points = question.get("expected_points", [])
            hint = points[0] if points else "先界定问题，再说明依据"
            if not chinese:
                hint = points[0] if points else "define the issue, then explain your evidence"
                return f'Here is a direction to consider: "{hint}". Please try the current question again.'
            return f"先给一个方向性提示：可以从“{hint}”开始组织。请重新回答当前问题。"
        if action == "ASK_FOLLOWUP":
            followup = decision.get("followup")
            if not followup:
                missing = analysis.get("missing_points") or ["关键依据"]
                followup = f"请进一步说明：{missing[0]}。"
            prefix = "我继续追问一下：" if chinese else "A follow-up question: "
            return f"{prefix}{followup}"
        if action == "MOVE_ON" and next_question:
            if not chinese:
                return f"Next question: {next_question['text']}"
            return f"好的，现有回答已经提供了基本判断依据。下一个问题：{next_question['text']}"
        if action == "END":
            if not chinese:
                return "This session is complete. Your evidence and feedback are being summarized."
            return "本轮答辩到此结束。系统正在汇总逐题证据、薄弱点和改进建议。"
        return "请继续。" if chinese else "Please continue."
