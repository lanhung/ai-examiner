(() => {
  "use strict";

  const TOKEN_HEADER = "X-AI-Examiner-Attempt-Token";
  const REQUEST_TIMEOUT_MS = 120000;
  const CODE_PATTERN = /^[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{6}$/;
  const ERROR_TEXT = {
    assignment_not_found: "入口码无效，请核对后重试。",
    assignment_closed: "本场考试已关闭。",
    assignment_scheduled: "本场考试尚未开放。",
    assignment_ended: "本场考试已结束。",
    attempt_limit_reached: "作答次数已用完。",
    learner_key_required: "请填写学号 / 考号。",
    attempt_not_found: "找不到这次作答，请重新输入入口码。",
    answer_too_long: "回答太长了，请精简到 4000 字以内。",
    rate_limited: "提交太频繁，请稍等几秒再试。",
  };
  const WINDOW_TEXT = {
    open: "考试进行中",
    scheduled: "尚未开放",
    ended: "已结束",
    closed: "已关闭",
  };

  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(window.location.search);
  const organizationId = params.get("org") || "";
  const MAX_ANSWER_LENGTH = 4000;
  const state = { code: "", assignment: null, attemptId: "", token: "", submitting: false };

  function storageKey(code) {
    return `ai-examiner-attempt:${organizationId}:${code}`;
  }

  // localStorage survives closing the in-app browser (e.g. WeChat), so a student
  // who reopens the link resumes the same attempt instead of starting a new one.
  function storage() {
    try {
      return window.localStorage;
    } catch (_error) {
      return null;
    }
  }

  function remember() {
    try {
      storage().setItem(
        storageKey(state.code),
        JSON.stringify({ attemptId: state.attemptId, token: state.token }),
      );
    } catch (_error) {
      // Resuming after a reload is a convenience only.
    }
  }

  function recall(code) {
    try {
      return JSON.parse(storage().getItem(storageKey(code)) || "null");
    } catch (_error) {
      return null;
    }
  }

  function forget(code) {
    try {
      storage().removeItem(storageKey(code));
    } catch (_error) {
      // Ignore unavailable storage.
    }
  }

  function normalizeCode(raw) {
    return String(raw || "").replace(/[\s\-_]+/g, "").toUpperCase();
  }

  async function api(path, options = {}) {
    const headers = { Accept: "application/json" };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (organizationId) headers["X-AI-Examiner-Organization"] = organizationId;
    if (state.token) headers[TOKEN_HEADER] = state.token;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), options.timeoutMs || REQUEST_TIMEOUT_MS);
    let response;
    try {
      response = await fetch(path, {
        method: options.method || "GET",
        headers,
        credentials: "same-origin",
        signal: controller.signal,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
      });
    } catch (_error) {
      const error = new Error("网络不稳定，请检查网络后重试。你的回答不会丢失。");
      error.code = "network";
      throw error;
    } finally {
      clearTimeout(timer);
    }
    let payload = null;
    try {
      payload = await response.json();
    } catch (_error) {
      payload = null;
    }
    if (!response.ok) {
      const detail = payload && payload.detail;
      const code = detail && typeof detail === "object" ? detail.code : "";
      const error = new Error(
        ERROR_TEXT[code]
          || (response.status === 429 ? "提交太频繁，请稍等几秒再试。" : "")
          || (response.status >= 500 ? "服务器繁忙，请稍后重试。你的回答不会丢失。" : "")
          || "操作未成功，请稍后重试。",
      );
      error.code = code;
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function show(screen) {
    for (const id of ["screenCode", "screenChat", "screenReport"]) {
      $(id).classList.toggle("hidden", id !== screen);
    }
  }

  function setError(id, error) {
    $(id).textContent = error ? error.message || String(error) : "";
  }

  function windowText(view) {
    const parts = [WINDOW_TEXT[view.window_state] || ""];
    if (view.closes_at) {
      parts.push(`截止时间：${new Date(view.closes_at).toLocaleString()}`);
    }
    if (view.max_attempts > 1) parts.push(`最多可作答 ${view.max_attempts} 次`);
    return parts.filter(Boolean).join(" · ");
  }

  function appendTurn(turn) {
    const bubble = document.createElement("div");
    bubble.className = `bubble ${turn.role === "user" ? "learner" : "examiner"}`;
    bubble.textContent = turn.content;
    $("chatLog").appendChild(bubble);
    bubble.scrollIntoView({ block: "end", behavior: "smooth" });
  }

  function listSection(title, items) {
    if (!items || !items.length) return null;
    const wrapper = document.createElement("div");
    const heading = document.createElement("h3");
    heading.textContent = title;
    const list = document.createElement("ul");
    for (const item of items) {
      const entry = document.createElement("li");
      entry.textContent = item;
      list.appendChild(entry);
    }
    wrapper.append(heading, list);
    return wrapper;
  }

  function renderReport(report) {
    const body = $("reportBody");
    body.replaceChildren();
    if (!report.results_available) {
      $("reportTitle").textContent = "已提交";
      const note = document.createElement("p");
      note.className = "muted";
      note.textContent = "你的作答已提交。老师公布结果后，可在此页面查看。";
      body.appendChild(note);
      $("reportRefresh").classList.remove("hidden");
      return;
    }
    $("reportTitle").textContent = "作答结果";
    $("reportRefresh").classList.add("hidden");
    const summary = report.summary || {};
    const score = document.createElement("div");
    score.className = "score";
    score.textContent = `${summary.overall_score ?? "-"} / ${summary.max_score ?? "-"}`;
    const answered = document.createElement("p");
    answered.className = "muted";
    answered.textContent = `已回答 ${summary.questions_answered ?? 0} 题`;
    body.append(score, answered);
    for (const section of [
      listSection("做得好的地方", report.strengths),
      listSection("需要加强", report.improvements),
      listSection("下一步建议", report.recommended_actions),
    ]) {
      if (section) body.appendChild(section);
    }
    if (report.disclaimer) {
      const disclaimer = document.createElement("p");
      disclaimer.className = "muted";
      disclaimer.textContent = report.disclaimer;
      body.appendChild(disclaimer);
    }
  }

  async function openReport() {
    show("screenReport");
    setError("reportError", null);
    try {
      renderReport(await api(`/api/attempts/${state.attemptId}/report`));
    } catch (error) {
      setError("reportError", error);
    }
  }

  function openChat(attempt) {
    $("chatTitle").textContent = attempt.assignment.title;
    $("chatLog").replaceChildren();
    for (const turn of attempt.turns) appendTurn(turn);
    show("screenChat");
    $("answerInput").focus();
  }

  async function resume(code) {
    const saved = recall(code);
    if (!saved || !saved.attemptId || !saved.token) return false;
    state.attemptId = saved.attemptId;
    state.token = saved.token;
    try {
      const attempt = await api(`/api/attempts/${state.attemptId}`);
      if (attempt.status === "submitted") {
        await openReport();
      } else if (attempt.status === "not_started") {
        const started = await api(`/api/attempts/${state.attemptId}/start`, {
          method: "POST",
          body: {},
        });
        attempt.turns.push(started.turn);
        openChat(attempt);
      } else {
        openChat(attempt);
      }
      return true;
    } catch (_error) {
      forget(code);
      state.attemptId = "";
      state.token = "";
      return false;
    }
  }

  async function lookup(rawCode) {
    setError("codeError", null);
    const code = normalizeCode(rawCode);
    if (!CODE_PATTERN.test(code)) {
      setError("codeError", new Error("入口码为 6 位字母或数字。"));
      return;
    }
    state.code = code;
    $("codeInput").value = code;
    if (window.location.pathname !== `/x/${code}`) {
      const query = organizationId ? `?org=${encodeURIComponent(organizationId)}` : "";
      window.history.replaceState(null, "", `/x/${code}${query}`);
    }
    if (await resume(code)) return;
    try {
      const view = await api(`/api/join/${code}`);
      state.assignment = view;
      $("joinTitle").textContent = view.title;
      $("joinWindow").textContent = windowText(view);
      $("joinIntro").textContent = view.intro_text || "";
      $("learnerKeyField").classList.toggle("hidden", !view.require_learner_key);
      $("learnerKey").required = Boolean(view.require_learner_key);
      $("attemptSubmit").disabled = view.window_state !== "open";
      $("joinDetails").classList.remove("hidden");
      $("displayName").focus();
    } catch (error) {
      $("joinDetails").classList.add("hidden");
      setError("codeError", error);
    }
  }

  async function beginAttempt() {
    setError("codeError", null);
    $("attemptSubmit").disabled = true;
    try {
      const created = await api(`/api/join/${state.code}/attempts`, {
        method: "POST",
        body: {
          display_name: $("displayName").value.trim(),
          learner_key: $("learnerKey").value.trim() || null,
        },
      });
      state.attemptId = created.attempt.id;
      state.token = created.attempt_token;
      remember();
      const started = await api(`/api/attempts/${state.attemptId}/start`, {
        method: "POST",
        body: {},
      });
      created.attempt.turns.push(started.turn);
      openChat(created.attempt);
    } catch (error) {
      setError("codeError", error);
    } finally {
      $("attemptSubmit").disabled = false;
    }
  }

  function showThinking() {
    const bubble = document.createElement("div");
    bubble.className = "bubble examiner thinking";
    bubble.id = "thinkingBubble";
    bubble.setAttribute("role", "status");
    bubble.textContent = "考官正在思考";
    $("chatLog").appendChild(bubble);
    bubble.scrollIntoView({ block: "end", behavior: "smooth" });
  }

  function hideThinking() {
    const bubble = $("thinkingBubble");
    if (bubble) bubble.remove();
  }

  // After a failed request the server may still have accepted the answer.
  // Re-read the attempt instead of blindly resubmitting (which would count twice).
  async function reconcile(answer) {
    try {
      const attempt = await api(`/api/attempts/${state.attemptId}`);
      const learnerTurns = attempt.turns.filter((turn) => turn.role === "user");
      const last = learnerTurns[learnerTurns.length - 1];
      if (last && last.content.trim() === answer) {
        $("chatLog").replaceChildren();
        for (const turn of attempt.turns) appendTurn(turn);
        $("answerInput").value = "";
        if (attempt.status === "submitted") await openReport();
        return true;
      }
    } catch (_error) {
      // Keep the answer in the box so the student can retry.
    }
    return false;
  }

  function updateCounter() {
    const length = $("answerInput").value.length;
    $("answerCounter").textContent = `${length} / ${MAX_ANSWER_LENGTH}`;
  }

  async function submitAnswer() {
    const answer = $("answerInput").value.trim();
    if (!answer || state.submitting) return;
    state.submitting = true;
    setError("chatError", null);
    $("answerSubmit").disabled = true;
    $("answerInput").readOnly = true;
    const pending = document.createElement("div");
    pending.className = "bubble learner";
    pending.textContent = answer;
    $("chatLog").appendChild(pending);
    showThinking();
    try {
      const result = await api(`/api/attempts/${state.attemptId}/answers`, {
        method: "POST",
        body: { answer },
      });
      hideThinking();
      pending.remove();
      $("answerInput").value = "";
      updateCounter();
      for (const turn of result.turns) appendTurn(turn);
      if (result.completed) await openReport();
    } catch (error) {
      hideThinking();
      pending.remove();
      if (!(await reconcile(answer))) {
        if (error.status === 409 && error.code !== "assignment_closed"
            && error.code !== "assignment_ended") {
          await openReport();
        } else {
          setError("chatError", error);
        }
      }
    } finally {
      state.submitting = false;
      $("answerSubmit").disabled = false;
      $("answerInput").readOnly = false;
    }
  }

  $("codeForm").addEventListener("submit", (event) => {
    event.preventDefault();
    lookup($("codeInput").value);
  });
  $("attemptForm").addEventListener("submit", (event) => {
    event.preventDefault();
    beginAttempt();
  });
  $("answerForm").addEventListener("submit", (event) => {
    event.preventDefault();
    submitAnswer();
  });
  $("reportRefresh").addEventListener("click", () => openReport());
  $("answerInput").addEventListener("input", updateCounter);
  $("answerInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      submitAnswer();
    }
  });

  const pathMatch = window.location.pathname.match(/^\/x\/([^/]+)\/?$/);
  const initialCode = pathMatch ? decodeURIComponent(pathMatch[1]) : params.get("code");
  if (initialCode) lookup(initialCode);
})();
