const state = {
  projectId: null,
  documentId: null,
  blueprintId: null,
  datasetId: null,
  sessionId: null,
  providers: [],
  documents: [],
  voiceConfig: null,
  voiceSessionId: null,
  voicePeer: null,
  voiceChannel: null,
  voiceStream: null,
  voiceAudio: null,
  voiceSocket: null,
  voiceAudioContext: null,
  voiceInputSource: null,
  voiceInputProcessor: null,
  voiceSilentGain: null,
  voicePlaybackSources: [],
  voicePlaybackTime: 0,
  voiceMuted: false,
  voicePtt: false,
  voiceStartedAt: 0,
  voiceFirstResponseRecorded: false,
  voiceInitialResponseSent: false,
  voiceProvider: "openai",
  voiceClientConfig: null,
  voiceMode: "",
};
const $ = (id) => document.getElementById(id);

function ensureVoiceProviderControl() {
  if ($("voiceProvider")) return;
  const settings = document.querySelector(".voice-settings");
  if (!settings) return;
  const label = document.createElement("label");
  label.textContent = "语音模型";
  const select = document.createElement("select");
  select.id = "voiceProvider";
  label.appendChild(select);
  settings.prepend(label);
}

function setStatus(id, text, kind = "") {
  const node = $(id);
  node.textContent = text;
  node.className = `status ${kind}`;
}
async function api(path, options = {}) {
  const response = await fetch(path, options);
  let body;
  try { body = await response.json(); } catch { body = { detail: await response.text() }; }
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[char]));
}
function list(items, fallback = "暂无") {
  return (items && items.length ? items : [fallback])
    .map((item) => `<li>${escapeHtml(String(item))}</li>`).join("");
}
function selectedProfiles() {
  return [...document.querySelectorAll("input[name='modelProfile']:checked")].map((node) => node.value);
}

function selectedVoiceProvider() {
  const providers = state.voiceConfig && state.voiceConfig.providers ? state.voiceConfig.providers : [];
  return providers.find((item) => item.id === $("voiceProvider").value) || providers[0] || null;
}

function syncVoiceProvider() {
  const provider = selectedVoiceProvider();
  if (!provider) return;
  state.voiceProvider = provider.id;
  $("voiceSelect").innerHTML = provider.voices
    .map((voice) => `<option value="${escapeHtml(voice)}">${escapeHtml(voice)}</option>`).join("");
  $("voiceSelect").value = provider.default_voice;
  $("startVoice").disabled = !(state.blueprintId && provider.ready);
  if (!window.isSecureContext && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
    $("voicePrereq").innerHTML = "<span class=\"secure-warning\">当前不是 HTTPS，浏览器可能拒绝麦克风。请使用域名 + HTTPS。</span>";
  } else if (!provider.ready) {
    $("voicePrereq").textContent = `${provider.label} 尚未配置，当前不可用。`;
  } else {
    const pttNote = provider.supports_ptt ? "" : "；此模型使用自然对话模式";
    const turnNote = provider.max_dialog_turns ? `；单次最多 ${provider.max_dialog_turns} 轮` : "";
    $("voicePrereq").textContent = `${provider.label} · ${provider.model} 已就绪；默认声音 ${provider.default_voice}${pttNote}${turnNote}。`;
  }
}
function syncConsensus() {
  const selected = selectedProfiles();
  const select = $("consensusProfile");
  const previous = select.value;
  select.innerHTML = selected.map((profile) => `<option value="${escapeHtml(profile)}">${escapeHtml(profile)}</option>`).join("");
  if (selected.includes(previous)) select.value = previous;
  $("generateGolden").disabled = !state.documentId || selected.length === 0;
}
function addMessage(turn) {
  const messages = $("messages");
  if (messages.querySelector(".empty")) messages.innerHTML = "";
  const wrapper = document.createElement("div");
  wrapper.className = `message ${turn.role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = turn.content;
  const meta = document.createElement("div");
  meta.className = "meta";
  const score = turn.evaluation ? ` · 评分 ${turn.evaluation.score}/5` : "";
  meta.textContent = `${turn.role === "assistant" ? "AI 考官" : "我"}${score}`;
  wrapper.append(bubble, meta);
  messages.appendChild(wrapper);
  messages.scrollTop = messages.scrollHeight;
}

async function loadEnvironment() {
  try {
    const [health, providers, voiceConfig] = await Promise.all([api("/health"), api("/api/providers"), api("/api/voice/config")]);
    state.voiceConfig = voiceConfig;
    state.providers = providers;
    $("providerBadge").textContent = `${health.provider} · ${health.model} · v${health.version}`;
    if (!health.provider_ready) $("providerBadge").textContent += " · 未配置";
    const modelList = $("modelProfiles");
    modelList.innerHTML = providers.map((provider, index) => {
      const checked = provider.provider === "mock" ? "checked" : "";
      const disabled = provider.ready ? "" : "disabled";
      const price = provider.provider === "mock"
        ? "零成本"
        : `$${provider.input_usd_per_million}/$${provider.output_usd_per_million} 每百万输入/输出 token`;
      return `<label class="model-option ${provider.ready ? "" : "unavailable"}">
        <input type="checkbox" name="modelProfile" value="${escapeHtml(provider.id)}" ${checked} ${disabled} />
        <span><strong>${escapeHtml(provider.label)}</strong><small>${escapeHtml(provider.recommended_for)} · ${price}${provider.ready ? "" : " · 未就绪"}</small></span>
      </label>`;
    }).join("");
    document.querySelectorAll("input[name='modelProfile']").forEach((node) => node.addEventListener("change", syncConsensus));
    syncConsensus();
    const readyProviders = providers.filter((provider) => provider.ready);
    const readyProviderOptions = readyProviders.map((provider) =>
      `<option value="${escapeHtml(provider.id)}">${escapeHtml(provider.label)}</option>`
    ).join("");
    $("blueprintProfile").innerHTML = readyProviderOptions;
    $("textProfile").innerHTML = readyProviderOptions;
    const preferredProvider = readyProviders.find((provider) => provider.provider === "ollama")
      || readyProviders.find((provider) => provider.provider !== "mock")
      || readyProviders[0];
    if (preferredProvider) {
      $("blueprintProfile").value = preferredProvider.id;
      $("textProfile").value = preferredProvider.id;
    }
    $("voiceProvider").innerHTML = voiceConfig.providers.map((provider) =>
      `<option value="${escapeHtml(provider.id)}" ${provider.ready ? "" : "disabled"}>${escapeHtml(provider.label)}${provider.ready ? "" : "（未配置）"}</option>`
    ).join("");
    $("voiceProvider").value = voiceConfig.provider;
    $("voiceProvider").onchange = syncVoiceProvider;
    syncVoiceProvider();
  } catch (error) {
    $("providerBadge").textContent = "服务不可用";
    $("modelProfiles").textContent = error.message;
  }
}

$("createProject").onclick = async () => {
  setStatus("projectStatus", "正在创建…");
  try {
    const project = await api("/api/projects", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name: $("projectName").value}),
    });
    state.projectId = project.id;
    $("documentFile").disabled = false;
    $("uploadDocument").disabled = false;
    setStatus("projectStatus", `项目已创建：${project.name}`, "success");
  } catch (error) { setStatus("projectStatus", error.message, "error"); }
};

$("uploadDocument").onclick = async () => {
  const file = $("documentFile").files[0];
  if (!file) return setStatus("documentStatus", "请选择文件", "error");
  setStatus("documentStatus", "正在上传和解析…");
  const form = new FormData();
  form.append("file", file);
  try {
    const documentData = await api(`/api/projects/${state.projectId}/documents`, {method: "POST", body: form});
    state.documentId = documentData.id;
    state.documents.push(documentData);
    $("generateBlueprint").disabled = false;
    $("generateGolden").disabled = selectedProfiles().length === 0;
    $("loadEvidence").disabled = false;
    $("analyzeVisual").disabled = false;
    $("runJoint").disabled = state.documents.length < 2;
    $("evidenceState").textContent = `${documentData.page_count} 页 · ${documentData.evidence_count} 个证据`;
    $("documentList").innerHTML = state.documents.map((doc) => `<div>${escapeHtml(doc.filename)} · ${doc.page_count} 页 · ${doc.evidence_count} 证据</div>`).join("");
    const warnings = documentData.warnings.length ? `；${documentData.warnings.join("；")}` : "";
    setStatus("documentStatus", `解析完成：${documentData.document_kind} · ${documentData.char_count.toLocaleString()} 字符${warnings}`, documentData.warnings.length ? "" : "success");
    await loadEvidence();
  } catch (error) { setStatus("documentStatus", error.message, "error"); }
};

$("generateBlueprint").onclick = async () => {
  const profile = $("blueprintProfile").value;
  if (!profile) return setStatus("blueprintStatus", "请选择已就绪的蓝图模型", "error");
  setStatus("blueprintStatus", `各 Agent 正在使用 ${profile} 生成并检查蓝图…`);
  try {
    const blueprint = await api(`/api/projects/${state.projectId}/blueprints`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({document_id: state.documentId, profile}),
    });
    state.blueprintId = blueprint.id;
    if ([...$("textProfile").options].some((option) => option.value === profile)) {
      $("textProfile").value = profile;
    }
    $("startSession").disabled = false;
    const voiceProvider = selectedVoiceProvider();
    $("startVoice").disabled = !(voiceProvider && voiceProvider.ready);
    setStatus("blueprintStatus", `蓝图 v${blueprint.version} 已生成：${blueprint.provider} · ${blueprint.model}，共 ${blueprint.data.questions.length} 个问题`, "success");
    const preview = $("blueprintPreview");
    preview.classList.remove("hidden");
    preview.innerHTML = `<strong>${escapeHtml(blueprint.data.title)}</strong><p>${escapeHtml(blueprint.data.summary)}</p><ol>${blueprint.data.questions.map((question) => `<li>${escapeHtml(question.text)}</li>`).join("")}</ol>`;
  } catch (error) { setStatus("blueprintStatus", error.message, "error"); }
};

function renderQuality(dataset) {
  const quality = dataset.quality_metrics;
  $("datasetState").textContent = `${dataset.status} · v${dataset.version}`;
  $("qualityMetrics").innerHTML = [
    ["题目数", quality.case_count],
    ["材料忠实率", `${Math.round(quality.grounded_rate * 100)}%`],
    ["标注完整率", `${Math.round(quality.annotation_completeness * 100)}%`],
    ["类型覆盖", quality.type_coverage],
    ["AI Panel", quality.mean_ai_panel_score ?? "—"],
    ["估算费用", `$${Number(quality.total_estimated_cost_usd || 0).toFixed(4)}`],
  ].map(([label, value]) => `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
}

$("generateGolden").onclick = async () => {
  const profiles = selectedProfiles();
  if (!profiles.length) return setStatus("goldenStatus", "至少选择一个已配置模型", "error");
  $("generateGolden").disabled = true;
  setStatus("goldenStatus", "正在独立标注、交叉批评、合成共识和生成测试回答…");
  try {
    const dataset = await api(`/api/projects/${state.projectId}/golden-datasets`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        document_id: state.documentId,
        profiles,
        consensus_profile: $("consensusProfile").value,
        question_count: Number($("questionCount").value),
      }),
    });
    state.datasetId = dataset.id;
    renderQuality(dataset);
    const preview = $("goldenPreview");
    preview.classList.remove("hidden");
    preview.innerHTML = `<strong>${escapeHtml(dataset.data.paper_title)}</strong><p>${escapeHtml(dataset.data.scope_summary)}</p><ol>${dataset.data.cases.slice(0, 8).map((item) => `<li><b>${escapeHtml(item.type)}</b> · ${escapeHtml(item.question)}<small>${escapeHtml(item.rationale)}</small></li>`).join("")}</ol>`;
    $("runBenchmark").disabled = false;
    $("freezeDataset").disabled = false;
    $("exportGolden").href = `/api/golden-datasets/${dataset.id}/export`;
    $("exportGolden").classList.remove("hidden");
    setStatus("goldenStatus", `Golden Dataset v${dataset.version} 已生成；状态：${dataset.status}`, dataset.status === "ready" ? "success" : "");
  } catch (error) {
    setStatus("goldenStatus", error.message, "error");
  } finally {
    $("generateGolden").disabled = false;
  }
};

$("runBenchmark").onclick = async () => {
  const profiles = selectedProfiles();
  if (!profiles.length) return setStatus("benchmarkStatus", "至少选择一个模型", "error");
  $("runBenchmark").disabled = true;
  setStatus("benchmarkStatus", "正在运行 Planner 与 Analyzer 基准；真实模型可能产生 API 费用…");
  try {
    const benchmark = await api(`/api/golden-datasets/${state.datasetId}/benchmarks`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({profiles, case_limit: 4, run_planner: true, run_analyzer: true}),
    });
    const results = $("benchmarkResults");
    results.classList.remove("hidden");
    results.innerHTML = `<table><thead><tr><th>#</th><th>模型</th><th>质量</th><th>Planner</th><th>Analyzer</th><th>延迟</th><th>费用</th></tr></thead><tbody>${benchmark.results.map((row) => `<tr>
      <td>${row.rank}</td><td><strong>${escapeHtml(row.profile)}</strong></td><td>${row.quality_score}</td>
      <td>${row.planner ? row.planner.score : "—"}</td><td>${row.analyzer ? row.analyzer.score : "—"}</td>
      <td>${(row.latency_ms / 1000).toFixed(2)}s</td><td>$${Number(row.estimated_cost_usd).toFixed(4)}</td>
    </tr>`).join("")}</tbody></table>`;
    setStatus("benchmarkStatus", `基准完成；当前第一名：${benchmark.summary.winner}`, "success");
  } catch (error) {
    setStatus("benchmarkStatus", error.message, "error");
  } finally {
    $("runBenchmark").disabled = false;
  }
};

$("startSession").onclick = async () => {
  const profile = $("textProfile").value;
  if (!profile) return window.alert("请选择已就绪的文本答辩模型");
  try {
    const session = await api("/api/sessions", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({project_id: state.projectId, blueprint_id: state.blueprintId, profile, question_limit: 6, max_followups_per_question: 2}),
    });
    state.sessionId = session.id;
    const started = await api(`/api/sessions/${session.id}/start`, {method: "POST"});
    addMessage(started.turn);
    $("answerInput").disabled = false;
    $("sendAnswer").disabled = false;
    $("sessionState").textContent = "答辩进行中";
    $("answerInput").focus();
  } catch (error) { window.alert(error.message); }
};

$("answerForm").onsubmit = async (event) => {
  event.preventDefault();
  const answer = $("answerInput").value.trim();
  if (!answer) return;
  $("sendAnswer").disabled = true;
  $("answerInput").disabled = true;
  $("answerHint").textContent = "Answer Analyzer、Evaluator 和 Policy Controller 正在协作…";
  try {
    const result = await api(`/api/sessions/${state.sessionId}/answers`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({answer}),
    });
    result.turns.forEach(addMessage);
    $("answerInput").value = "";
    if (result.completed) {
      $("sessionState").textContent = "已完成";
      await showReport();
    } else {
      $("sendAnswer").disabled = false;
      $("answerInput").disabled = false;
      $("answerInput").focus();
      $("answerHint").textContent = result.decision.action === "ASK_FOLLOWUP" ? "当前为追问，请直接回应追问。" : "一次只回答当前问题。";
    }
  } catch (error) {
    window.alert(error.message);
    $("sendAnswer").disabled = false;
    $("answerInput").disabled = false;
  }
};

async function showReport() {
  const report = await api(`/api/sessions/${state.sessionId}/report`);
  $("reportPanel").classList.remove("hidden");
  $("reportContent").innerHTML = `
    <div class="score-card"><div class="score">${report.overall_score}<small>/5</small></div><div><strong>风险等级：${escapeHtml(report.risk_level)}</strong><p>已评估 ${report.questions_answered} 次回答</p></div></div>
    <div class="report-grid">
      <div class="report-block"><h3>优先薄弱点</h3><ul>${list(report.priority_weaknesses, "暂未识别明显薄弱点")}</ul></div>
      <div class="report-block"><h3>建议动作</h3><ul>${list(report.recommended_actions)}</ul></div>
      <div class="report-block"><h3>高分证据</h3><ul>${list(report.strengths, "尚无达到高分阈值的回答")}</ul></div>
      <div class="report-block"><h3>分类型表现</h3><ul>${Object.entries(report.dimension_summary).map(([key, value]) => `<li>${escapeHtml(key)}：${value}/5</li>`).join("") || "<li>暂无</li>"}</ul></div>
    </div>
    <div class="report-block"><h3>问题与原始证据</h3><div class="evidence-report-grid">${(report.evidence || []).map((item) => `<article>
      ${item.page_preview_url ? `<a href="${item.page_preview_url}" target="_blank"><img src="${item.page_preview_url}" alt="第 ${item.source_page || "?"} 页证据" /></a>` : ""}
      <strong>${escapeHtml(item.question_id || "问题")}</strong><small>第 ${escapeHtml(item.source_page || "?")} 页 · 得分 ${escapeHtml(item.score)}</small>
      <p>${escapeHtml(item.source_excerpt || "未记录来源片段")}</p>
    </article>`).join("") || "<p>暂无页面证据。</p>"}</div></div>
    <p>${escapeHtml(report.disclaimer)}</p>`;
  $("reportPanel").scrollIntoView({behavior: "smooth"});
}

async function loadEvidence() {
  if (!state.documentId) return;
  setStatus("evidenceStatus", "正在读取页面与区域证据…");
  try {
    const result = await api(`/api/documents/${state.documentId}/evidence`);
    const pages = result.assets.filter((asset) => asset.kind === "page");
    $("evidenceGallery").innerHTML = pages.map((asset) => `<article class="evidence-card">
      <img loading="lazy" src="${asset.file_url}" alt="${escapeHtml(asset.label)}" />
      <div class="content"><strong>${escapeHtml(asset.label)}</strong><small>第 ${asset.page_number} 页 · ${escapeHtml(asset.metadata.format || asset.kind)}</small></div>
    </article>`).join("") || `<div class="empty compact">没有可显示的页面预览。</div>`;
    setStatus("evidenceStatus", `已加载 ${result.assets.length} 个证据对象，其中 ${pages.length} 个页面/幻灯片。`, "success");
  } catch (error) { setStatus("evidenceStatus", error.message, "error"); }
}

async function pollJob(jobId) {
  for (let attempt = 0; attempt < 180; attempt += 1) {
    const job = await api(`/api/jobs/${jobId}`);
    setStatus("evidenceStatus", `${job.message || job.status} · ${Math.round(job.progress * 100)}%`);
    if (job.status === "completed") return job;
    if (job.status === "failed") throw new Error(job.error || "后台任务失败");
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error("后台任务等待超时，请稍后在任务接口检查状态");
}

$("loadEvidence").onclick = loadEvidence;

$("analyzeVisual").onclick = async () => {
  if (!state.documentId) return;
  const profile = $("consensusProfile").value || selectedProfiles()[0] || "mock:heuristic-v2";
  $("analyzeVisual").disabled = true;
  setStatus("evidenceStatus", "正在提交视觉证据分析任务…");
  try {
    const response = await api(`/api/documents/${state.documentId}/visual-analyses`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({profile, max_pages: 10, asynchronous: true}),
    });
    if (response.job) await pollJob(response.job.id);
    const analyses = await api(`/api/documents/${state.documentId}/visual-analyses`);
    const box = $("visualResults");
    box.classList.remove("hidden");
    box.innerHTML = `<strong>视觉审查结果</strong>${analyses.slice(0, 10).map((item) => `<div class="report-block">
      <h3>第 ${item.data.page_number || "?"} 页 · ${escapeHtml(item.data.visual_type || "page")}</h3>
      <p>${escapeHtml(item.data.summary || "")}</p>
      <ul>${list(item.data.potential_issues || [])}</ul>
      <ol>${(item.data.exam_questions || []).map((q) => `<li>${escapeHtml(q.question)}</li>`).join("")}</ol>
    </div>`).join("")}`;
    setStatus("evidenceStatus", `视觉分析完成：${analyses.length} 页。`, "success");
  } catch (error) { setStatus("evidenceStatus", error.message, "error"); }
  finally { $("analyzeVisual").disabled = false; }
};

$("runJoint").onclick = async () => {
  if (state.documents.length < 2) return;
  setStatus("evidenceStatus", "正在比较论文、PPT 和补充材料的一致性…");
  try {
    const profile = $("consensusProfile").value || selectedProfiles()[0] || "mock:heuristic-v2";
    const result = await api(`/api/projects/${state.projectId}/joint-analyses`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({document_ids: state.documents.map((doc) => doc.id), profile}),
    });
    const box = $("visualResults");
    box.classList.remove("hidden");
    box.innerHTML = `<strong>多文档联合审查</strong><p>${escapeHtml(result.data.package_summary)}</p>
      <h3>矛盾与遗漏</h3><ul>${list([...(result.data.contradictions || []), ...(result.data.omissions || [])])}</ul>
      <h3>高风险问题</h3><ol>${(result.data.high_risk_questions || []).map((q) => `<li>${escapeHtml(q.question)}</li>`).join("")}</ol>`;
    setStatus("evidenceStatus", "联合审查完成。", "success");
  } catch (error) { setStatus("evidenceStatus", error.message, "error"); }
};

$("showCosts").onclick = async () => {
  try {
    const data = await api(`/api/costs${state.projectId ? `?project_id=${state.projectId}` : ""}`);
    const box = $("costResults");
    box.classList.remove("hidden");
    box.innerHTML = `<strong>费用与预算</strong><p>估算费用：$${Number(data.estimated_cost_usd).toFixed(4)} / 预算 $${Number(data.budget_usd).toFixed(2)}</p>
      <ul>${Object.entries(data.by_model).map(([model, item]) => `<li>${escapeHtml(model)}：${item.calls} 次，$${Number(item.cost_usd).toFixed(4)}</li>`).join("") || "<li>尚无付费调用</li>"}</ul>`;
  } catch (error) { window.alert(error.message); }
};

$("freezeDataset").onclick = async () => {
  if (!state.datasetId) return;
  try {
    const result = await api(`/api/golden-datasets/${state.datasetId}/status`, {
      method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({status: "frozen"}),
    });
    $("datasetState").textContent = `${result.status} · v${result.version}`;
    $("freezeDataset").disabled = true;
    setStatus("benchmarkStatus", "数据集已冻结，可作为稳定回归基准。", "success");
  } catch (error) { setStatus("benchmarkStatus", error.message, "error"); }
};

ensureVoiceProviderControl();
loadEnvironment();

function setVoiceVisual(mode, text) {
  state.voiceMode = mode || "";
  const orb = $("voiceOrb");
  orb.className = `voice-orb ${mode || ""}`;
  $("voiceLiveText").textContent = text || "";
  const labels = {listening: "正在听", speaking: "AI 正在说", thinking: "正在思考", connected: "已连接", "": "待机"};
  $("voiceState").textContent = labels[mode] || mode || "待机";
}

function addVoiceTranscript(role, text) {
  const box = $("voiceTranscript");
  if (!text || !text.trim()) return;
  if (box.querySelector(".empty")) box.innerHTML = "";
  const line = document.createElement("div");
  line.className = `voice-line ${role}`;
  const strong = document.createElement("strong");
  strong.textContent = role === "assistant" ? "AI 考官" : "我";
  const content = document.createElement("div");
  content.textContent = text.trim();
  const small = document.createElement("small");
  small.textContent = new Date().toLocaleTimeString();
  line.append(strong, content, small);
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

async function persistVoiceEvent(eventType, role = null, text = "", latencyMs = null, raw = {}) {
  if (!state.voiceSessionId) return;
  try {
    await api(`/api/voice/sessions/${state.voiceSessionId}/events`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({event_type: eventType, role, text, latency_ms: latencyMs, raw}),
    });
  } catch (error) {
    console.warn("voice event persistence failed", error);
  }
}

function sendRealtimeEvent(payload) {
  if (state.voiceSocket && state.voiceSocket.readyState === WebSocket.OPEN) {
    state.voiceSocket.send(JSON.stringify(payload));
    return;
  }
  if (state.voiceChannel && state.voiceChannel.readyState === "open") {
    state.voiceChannel.send(JSON.stringify(payload));
  }
}

function floatAudioToPcm16Base64(samples, inputRate) {
  const ratio = inputRate / 16000;
  const outputLength = Math.max(1, Math.floor(samples.length / ratio));
  const bytes = new Uint8Array(outputLength * 2);
  const view = new DataView(bytes.buffer);
  for (let index = 0; index < outputLength; index += 1) {
    const start = Math.floor(index * ratio);
    const end = Math.min(samples.length, Math.floor((index + 1) * ratio));
    let sum = 0;
    for (let cursor = start; cursor < end; cursor += 1) sum += samples[cursor];
    const sample = Math.max(-1, Math.min(1, sum / Math.max(1, end - start)));
    view.setInt16(index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

function stopQwenPlayback() {
  state.voicePlaybackSources.forEach((source) => {
    try { source.stop(); } catch {}
  });
  state.voicePlaybackSources = [];
  state.voicePlaybackTime = state.voiceAudioContext ? state.voiceAudioContext.currentTime : 0;
}

function playQwenPcm(base64Audio) {
  const context = state.voiceAudioContext;
  if (!context || !base64Audio) return;
  const binary = atob(base64Audio);
  const sampleCount = Math.floor(binary.length / 2);
  const buffer = context.createBuffer(1, sampleCount, 24000);
  const channel = buffer.getChannelData(0);
  for (let index = 0; index < sampleCount; index += 1) {
    let value = binary.charCodeAt(index * 2) | (binary.charCodeAt(index * 2 + 1) << 8);
    if (value >= 0x8000) value -= 0x10000;
    channel[index] = value / 0x8000;
  }
  const source = context.createBufferSource();
  source.buffer = buffer;
  source.connect(context.destination);
  const startAt = Math.max(context.currentTime + 0.02, state.voicePlaybackTime);
  state.voicePlaybackTime = startAt + buffer.duration;
  state.voicePlaybackSources.push(source);
  source.onended = () => {
    state.voicePlaybackSources = state.voicePlaybackSources.filter((item) => item !== source);
  };
  source.start(startAt);
}

function sendInitialVoiceResponse() {
  if (state.voiceInitialResponseSent) return;
  state.voiceInitialResponseSent = true;
  if (state.voiceProvider === "openai") {
    sendRealtimeEvent({
      type: "conversation.item.create",
      item: {type: "message", role: "user", content: [{type: "input_text", text: "请开始本次答辩，用一句简短欢迎语后直接提出第一道问题。"}]},
    });
  }
  sendRealtimeEvent({type: "response.create", event_id: `event_start_${Date.now()}`});
}

function handleRealtimeEvent(event) {
  let data;
  try { data = JSON.parse(event.data); } catch { return; }
  const type = data.type || "unknown";
  if (type === "session.created" && state.voiceProvider === "qwen") {
    setVoiceVisual("connected", "千问语音通道已连接，正在载入答辩蓝图…");
    if (state.voiceClientConfig) sendRealtimeEvent(state.voiceClientConfig);
  } else if (type === "session.updated" && state.voiceProvider === "qwen") {
    if (state.voiceInitialResponseSent) {
      setVoiceVisual("connected", "千问语音设置已更新。");
    } else {
      setVoiceVisual("connected", "千问已载入答辩蓝图，正在开始第一道问题…");
      sendInitialVoiceResponse();
    }
  } else if (type === "session.created" || type === "session.updated") {
    setVoiceVisual("connected", "语音连接已就绪，AI 将开始第一道问题。您可以随时插话。 ");
  } else if (type === "input_audio_buffer.speech_started") {
    const interrupted = state.voiceMode === "speaking";
    if (state.voiceProvider === "qwen") stopQwenPlayback();
    setVoiceVisual("listening", "正在听您回答…");
    if (interrupted) persistVoiceEvent("interruption", null, "", null, {type});
  } else if (type === "input_audio_buffer.speech_stopped") {
    setVoiceVisual("thinking", "已听完，正在组织追问…");
  } else if (type === "response.created") {
    setVoiceVisual("thinking", "正在生成回应…");
  } else if (type === "response.output_audio_transcript.delta" || type === "response.audio_transcript.delta") {
    setVoiceVisual("speaking", data.delta || "AI 正在说…");
    if (!state.voiceFirstResponseRecorded) {
      state.voiceFirstResponseRecorded = true;
      const latency = Math.max(0, Date.now() - state.voiceStartedAt);
      persistVoiceEvent("first_response", null, "", latency, {type});
    }
  } else if (type === "response.audio.delta" && state.voiceProvider === "qwen") {
    playQwenPcm(data.delta || data.audio || "");
  } else if (type === "response.output_audio_transcript.done" || type === "response.audio_transcript.done") {
    const transcript = data.transcript || data.text || "";
    addVoiceTranscript("assistant", transcript);
    persistVoiceEvent("transcript", "assistant", transcript, null, {type, item_id: data.item_id});
    setVoiceVisual("connected", "轮到您回答。直接说话即可。 ");
  } else if (type === "conversation.item.input_audio_transcription.completed") {
    const transcript = data.transcript || "";
    addVoiceTranscript("user", transcript);
    persistVoiceEvent("transcript", "user", transcript, null, {type, item_id: data.item_id});
  } else if (type === "conversation.item.input_audio_transcription.delta") {
    const preview = `${data.text || ""}${data.stash || ""}`;
    if (preview) setVoiceVisual("listening", preview);
  } else if (type === "response.done") {
    setVoiceVisual("connected", "轮到您回答。直接说话即可。 ");
    const usage = data.response && data.response.usage ? data.response.usage : (data.usage || {});
    persistVoiceEvent("response_done", null, "", null, {type, usage});
  } else if (type === "error") {
    const message = data.error && data.error.message ? data.error.message : (data.message || "Realtime API 错误");
    setStatus("voiceStatus", message, "error");
    setVoiceVisual("", "连接出现错误，请结束后重试。 ");
    persistVoiceEvent("error", null, message, null, {type, error: data.error || {}});
  }
}

async function connectQwenVoice(voiceSession, stream) {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) throw new Error("当前浏览器不支持实时 PCM 音频处理");
  const context = new AudioContextClass();
  await context.resume();
  state.voiceAudioContext = context;
  state.voicePlaybackTime = context.currentTime;

  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/api/voice/sessions/${voiceSession.id}/qwen-ws`);
  state.voiceSocket = socket;
  socket.onmessage = handleRealtimeEvent;
  socket.onclose = () => {
    if (state.voiceSocket === socket && state.voiceSessionId) {
      setVoiceVisual("", "千问语音连接已关闭。");
    }
  };
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("连接千问实时语音超时")), 20000);
    socket.onopen = () => {
      clearTimeout(timeout);
      setVoiceVisual("connected", "已连接千问实时语音，正在初始化…");
      resolve();
    };
    socket.onerror = () => {
      clearTimeout(timeout);
      reject(new Error("无法连接千问实时语音代理"));
    };
  });

  const source = context.createMediaStreamSource(stream);
  const processor = context.createScriptProcessor(4096, 1, 1);
  const silentGain = context.createGain();
  silentGain.gain.value = 0;
  processor.onaudioprocess = (event) => {
    const audioTrack = stream.getAudioTracks()[0];
    if (state.voiceMuted || !audioTrack || !audioTrack.enabled || socket.readyState !== WebSocket.OPEN) return;
    const audio = floatAudioToPcm16Base64(event.inputBuffer.getChannelData(0), context.sampleRate);
    socket.send(JSON.stringify({
      type: "input_audio_buffer.append",
      event_id: `event_audio_${Date.now()}`,
      audio,
    }));
  };
  source.connect(processor);
  processor.connect(silentGain);
  silentGain.connect(context.destination);
  state.voiceInputSource = source;
  state.voiceInputProcessor = processor;
  state.voiceSilentGain = silentGain;
}

async function connectVoice() {
  if (!state.projectId || !state.blueprintId) throw new Error("请先创建项目、上传材料并生成蓝图");
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    throw new Error("当前浏览器不支持麦克风访问；请使用最新版 Chrome、Safari 或 Edge，并通过 HTTPS 访问");
  }
  if (!window.isSecureContext && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
    throw new Error("公网语音需要 HTTPS 安全连接。请配置域名和 Caddy 后再访问");
  }
  const provider = selectedVoiceProvider();
  if (!provider || !provider.ready) throw new Error("所选语音模型尚未配置");
  const voiceSession = await api("/api/voice/sessions", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      project_id: state.projectId,
      blueprint_id: state.blueprintId,
      provider: provider.id,
      mode: "defense",
      language: "zh-CN",
      voice: $("voiceSelect").value,
      vad_eagerness: $("vadSelect").value,
      question_limit: 6,
      max_followups: 2,
    }),
  });
  state.voiceSessionId = voiceSession.id;
  state.voiceStartedAt = Date.now();
  state.voiceFirstResponseRecorded = false;
  state.voiceInitialResponseSent = false;
  state.voiceProvider = provider.id;
  state.voiceClientConfig = voiceSession.client_config || null;

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1},
  });
  state.voiceStream = stream;
  if (provider.id === "qwen") {
    await connectQwenVoice(voiceSession, stream);
    $("muteVoice").disabled = false;
    $("togglePtt").disabled = !provider.supports_ptt;
    $("endVoice").disabled = false;
    $("startVoice").disabled = true;
    $("voiceProvider").disabled = true;
    $("voiceSelect").disabled = true;
    $("vadSelect").disabled = true;
    setStatus("voiceStatus", `${provider.label} 已连接。系统使用服务端 VAD 自动判断何时轮到 AI 回答。`, "success");
    return;
  }

  const pc = new RTCPeerConnection(provider.id === "qwen" ? {iceServers: []} : undefined);
  state.voicePeer = pc;
  const audio = document.createElement("audio");
  audio.autoplay = true;
  audio.playsInline = true;
  state.voiceAudio = audio;
  pc.ontrack = (event) => { audio.srcObject = event.streams[0]; };
  pc.onconnectionstatechange = () => {
    if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
      setVoiceVisual("", `连接状态：${pc.connectionState}`);
    }
  };

  stream.getAudioTracks().forEach((track) => pc.addTrack(track, stream));

  const handleChannelOpen = () => {
    setVoiceVisual("connected", "连接成功，AI 正在开始答辩…");
    if (provider.id === "openai") sendInitialVoiceResponse();
  };
  const attachVoiceChannel = (channel) => {
    state.voiceChannel = channel;
    channel.onmessage = handleRealtimeEvent;
    channel.onopen = handleChannelOpen;
    if (channel.readyState === "open") handleChannelOpen();
  };
  const negotiationChannel = pc.createDataChannel("oai-events");
  if (provider.id === "qwen") {
    pc.ondatachannel = (event) => attachVoiceChannel(event.channel);
  } else {
    attachVoiceChannel(negotiationChannel);
  }

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  if (provider.id === "qwen" && pc.iceGatheringState !== "complete") {
    await new Promise((resolve) => {
      const timeout = setTimeout(resolve, 5000);
      pc.addEventListener("icegatheringstatechange", () => {
        if (pc.iceGatheringState === "complete") {
          clearTimeout(timeout);
          resolve();
        }
      });
    });
  }
  const response = await fetch(`/api/voice/sessions/${voiceSession.id}/sdp`, {
    method: "POST",
    headers: {"Content-Type": "application/sdp"},
    body: pc.localDescription.sdp,
  });
  if (!response.ok) {
    let detail = await response.text();
    try { detail = JSON.parse(detail).detail || detail; } catch {}
    throw new Error(detail || `Realtime connection failed: ${response.status}`);
  }
  await pc.setRemoteDescription({type: "answer", sdp: await response.text()});
  $("muteVoice").disabled = false;
  $("togglePtt").disabled = !provider.supports_ptt;
  $("endVoice").disabled = false;
  $("startVoice").disabled = true;
  $("voiceProvider").disabled = true;
  $("voiceSelect").disabled = true;
  $("vadSelect").disabled = true;
  const vadLabel = provider.id === "qwen" ? "服务端 VAD" : "语义 VAD";
  setStatus("voiceStatus", `${provider.label} WebRTC 已连接。系统使用${vadLabel}自动判断何时轮到 AI 回答。`, "success");
}

async function endVoice(reason = "user_ended") {
  if (state.voiceChannel) state.voiceChannel.close();
  if (state.voicePeer) state.voicePeer.close();
  const socket = state.voiceSocket;
  state.voiceSocket = null;
  if (socket) socket.close();
  stopQwenPlayback();
  if (state.voiceInputProcessor) {
    state.voiceInputProcessor.onaudioprocess = null;
    try { state.voiceInputProcessor.disconnect(); } catch {}
  }
  if (state.voiceInputSource) {
    try { state.voiceInputSource.disconnect(); } catch {}
  }
  if (state.voiceSilentGain) {
    try { state.voiceSilentGain.disconnect(); } catch {}
  }
  if (state.voiceStream) state.voiceStream.getTracks().forEach((track) => track.stop());
  if (state.voiceAudio) state.voiceAudio.srcObject = null;
  if (state.voiceSessionId) {
    try {
      await api(`/api/voice/sessions/${state.voiceSessionId}/complete`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({reason}),
      });
    } catch (error) { console.warn(error); }
  }
  state.voicePeer = null;
  state.voiceChannel = null;
  if (state.voiceAudioContext) {
    try { await state.voiceAudioContext.close(); } catch {}
  }
  state.voiceAudioContext = null;
  state.voiceInputSource = null;
  state.voiceInputProcessor = null;
  state.voiceSilentGain = null;
  state.voicePlaybackSources = [];
  state.voicePlaybackTime = 0;
  state.voiceStream = null;
  state.voiceAudio = null;
  state.voiceClientConfig = null;
  state.voiceInitialResponseSent = false;
  state.voiceSessionId = null;
  state.voiceMuted = false;
  state.voicePtt = false;
  $("muteVoice").disabled = true;
  $("togglePtt").disabled = true;
  $("pttButton").disabled = true;
  $("pttButton").classList.add("hidden");
  $("endVoice").disabled = true;
  $("voiceProvider").disabled = false;
  $("voiceSelect").disabled = false;
  $("vadSelect").disabled = false;
  const provider = selectedVoiceProvider();
  $("startVoice").disabled = !(state.blueprintId && provider && provider.ready);
  setVoiceVisual("", "语音会话已结束，转录已保存。 ");
}

$("startVoice").onclick = async () => {
  $("startVoice").disabled = true;
  setStatus("voiceStatus", "正在申请麦克风权限并建立 WebRTC 连接…");
  try { await connectVoice(); }
  catch (error) {
    setStatus("voiceStatus", error.message, "error");
    await endVoice("connection_failed");
  }
};

$("muteVoice").onclick = () => {
  if (!state.voiceStream) return;
  state.voiceMuted = !state.voiceMuted;
  state.voiceStream.getAudioTracks().forEach((track) => { track.enabled = !state.voiceMuted && !state.voicePtt; });
  $("muteVoice").textContent = state.voiceMuted ? "恢复麦克风" : "静音麦克风";
  setStatus("voiceStatus", state.voiceMuted ? "麦克风已静音。" : "麦克风已恢复。", "success");
};

$("togglePtt").onclick = () => {
  if (!state.voiceStream) return;
  const provider = selectedVoiceProvider();
  if (!provider || !provider.supports_ptt) return;
  state.voicePtt = !state.voicePtt;
  const ptt = $("pttButton");
  if (state.voicePtt) {
    if (state.voiceProvider === "qwen") {
      sendRealtimeEvent({type: "session.update", event_id: `event_ptt_${Date.now()}`, session: {turn_detection: null}});
    } else {
      sendRealtimeEvent({type: "session.update", session: {audio: {input: {turn_detection: null}}}});
    }
    state.voiceStream.getAudioTracks().forEach((track) => { track.enabled = false; });
    ptt.classList.remove("hidden");
    ptt.disabled = false;
    $("togglePtt").textContent = "切换自然对话";
    setStatus("voiceStatus", "按住说话模式：按住蓝色按钮回答，松开后 AI 立即回应。", "success");
  } else {
    if (state.voiceProvider === "qwen") {
      const turnDetection = state.voiceClientConfig && state.voiceClientConfig.session
        ? state.voiceClientConfig.session.turn_detection
        : {type: "server_vad", threshold: 0.5, silence_duration_ms: 800};
      sendRealtimeEvent({type: "session.update", event_id: `event_vad_${Date.now()}`, session: {turn_detection: turnDetection}});
    } else {
      sendRealtimeEvent({type: "session.update", session: {audio: {input: {turn_detection: {type: "semantic_vad", eagerness: $("vadSelect").value, create_response: true, interrupt_response: true}}}}});
    }
    state.voiceStream.getAudioTracks().forEach((track) => { track.enabled = !state.voiceMuted; });
    ptt.classList.add("hidden");
    $("togglePtt").textContent = "切换按住说话";
    setStatus("voiceStatus", "已恢复自然语音模式。", "success");
  }
};

function pttDown(event) {
  event.preventDefault();
  if (!state.voicePtt || !state.voiceStream) return;
  $("pttButton").classList.add("active");
  sendRealtimeEvent({type: "input_audio_buffer.clear"});
  if (state.voiceMode === "speaking") sendRealtimeEvent({type: "response.cancel"});
  if (state.voiceProvider === "qwen") stopQwenPlayback();
  else sendRealtimeEvent({type: "output_audio_buffer.clear"});
  state.voiceStream.getAudioTracks().forEach((track) => { track.enabled = true; });
  setVoiceVisual("listening", "正在录入您的回答…");
}
function pttUp(event) {
  event.preventDefault();
  if (!state.voicePtt || !state.voiceStream) return;
  $("pttButton").classList.remove("active");
  state.voiceStream.getAudioTracks().forEach((track) => { track.enabled = false; });
  sendRealtimeEvent({type: "input_audio_buffer.commit"});
  sendRealtimeEvent({type: "response.create", event_id: `event_response_${Date.now()}`});
  setVoiceVisual("thinking", "正在回应…");
}
$("pttButton").addEventListener("pointerdown", pttDown);
$("pttButton").addEventListener("pointerup", pttUp);
$("pttButton").addEventListener("pointercancel", pttUp);
$("endVoice").onclick = () => endVoice("user_ended");
window.addEventListener("beforeunload", () => {
  if (state.voiceStream) state.voiceStream.getTracks().forEach((track) => track.stop());
});
