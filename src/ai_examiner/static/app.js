const state = {
  authMethod: "unknown",
  principal: null,
  organizations: [],
  organizationId: localStorage.getItem("ai-examiner.organization"),
  projectId: null,
  documentId: null,
  blueprintId: null,
  blueprintTemplateVersionId: null,
  blueprintJobId: null,
  blueprintRequestKey: null,
  datasetId: null,
  sessionId: null,
  learnerSubjectId: null,
  identityId: localStorage.getItem("ai-examiner-identity-id"),
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
  voiceInitialRequestAt: 0,
  voiceFirstResponseRecorded: false,
  voiceInitialResponseSent: false,
  voiceInputReady: false,
  voiceInitialResponseTimer: null,
  voiceProvider: "openai",
  voiceClientConfig: null,
  voiceMode: "",
  templates: [],
  publishedTemplates: [],
  selectedTemplate: null,
  selectedTemplateVersion: null,
  selectedTemplateSource: null,
  selectedTemplateVersionId: null,
  sessionTemplateSource: null,
  sessionTemplateLabel: "",
  templateRawDirty: false,
};
const $ = (id) => document.getElementById(id);

const preferenceOptions = {
  explanation_style: [["concise", "简洁"], ["step_by_step", "分步"], ["example_first", "先举例"]],
  response_pace: [["fast", "快速"], ["balanced", "平衡"], ["deliberate", "留出思考时间"]],
  interruption_style: [["minimal", "尽量少打断"], ["balanced", "平衡"], ["strict", "严格纠偏"]],
  hint_style: [["none", "不给提示"], ["progressive", "逐步提示"], ["direct", "直接提示"]],
  interface_language: [["zh-CN", "中文"], ["en", "English"]],
};

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
function responseErrorMessage(body, status) {
  const detail = body && typeof body === "object" && "detail" in body ? body.detail : body;
  const rawMessage = detail && typeof detail === "object" ? detail.message : detail;
  if (String(rawMessage || "").includes("MEMORY_IDENTITY_SECRET")) {
    return "长期记忆尚未由管理员启用；其他答辩功能不受影响。";
  }
  if (detail && typeof detail === "object") {
    return `${detail.code ? `${detail.code}: ` : ""}${detail.message || JSON.stringify(detail)}`;
  }
  return detail || `HTTP ${status}`;
}
async function api(path, options = {}) {
  const {organizationScoped = true, headers: optionHeaders = {}, ...fetchOptions} = options;
  const headers = {...optionHeaders};
  if (organizationScoped && state.organizationId) {
    headers["X-AI-Examiner-Organization"] = state.organizationId;
  }
  const response = await fetch(path, {
    cache: "no-store",
    credentials: "same-origin",
    ...fetchOptions,
    headers,
  });
  const raw = await response.text();
  let body = {};
  if (raw) {
    try { body = JSON.parse(raw); } catch { body = { detail: raw }; }
  }
  if (!response.ok) {
    throw new Error(responseErrorMessage(body, response.status));
  }
  return body;
}

function isOidcAuthMethod(method) {
  return method === "oidc" || String(method || "").startsWith("oidc_");
}

function showWorkbenchLogin() {
  $("workbenchLogin").classList.remove("hidden");
  $("workbenchIdentity").classList.add("hidden");
  $("providerBadge").textContent = "请先登录";
  $("createProject").disabled = true;
}

function activateWorkbenchOrganization(organizationId) {
  state.organizationId = organizationId || null;
  if (state.organizationId) {
    localStorage.setItem("ai-examiner.organization", state.organizationId);
  } else {
    localStorage.removeItem("ai-examiner.organization");
  }
}

async function bootstrapWorkbenchIdentity() {
  try {
    const me = await api("/api/v1/me", {organizationScoped: false});
    state.authMethod = me.authentication?.method || "unknown";
    state.principal = me.principal || null;
    state.organizations = (me.organizations || []).filter((item) => item.status === "active");
    if (isOidcAuthMethod(state.authMethod) && !state.principal) {
      showWorkbenchLogin();
      return false;
    }
    if (!isOidcAuthMethod(state.authMethod)) return true;
    if (!state.organizations.length) {
      showWorkbenchLogin();
      $("providerBadge").textContent = "当前账号没有可用组织";
      return false;
    }
    const selected = state.organizations.some((item) => item.id === state.organizationId)
      ? state.organizationId
      : state.organizations[0].id;
    const select = $("workbenchOrganization");
    select.innerHTML = state.organizations.map((item) =>
      `<option value="${escapeHtml(item.id)}">${escapeHtml(item.display_name || item.slug || item.id)} · ${escapeHtml(item.role || "member")}</option>`
    ).join("");
    select.value = selected;
    select.onchange = () => {
      activateWorkbenchOrganization(select.value);
      window.location.reload();
    };
    activateWorkbenchOrganization(selected);
    $("workbenchPrincipal").textContent = state.principal.display_name || "已登录";
    $("workbenchIdentity").classList.remove("hidden");
    $("workbenchLogin").classList.add("hidden");
    return true;
  } catch (error) {
    showWorkbenchLogin();
    $("providerBadge").textContent = error.message || "身份服务不可用";
    return false;
  }
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

function localized(value) {
  if (!value || typeof value !== "object") return String(value || "");
  return value["zh-CN"] || value.en || Object.values(value)[0] || "";
}

function templateMode() {
  return state.sessionTemplateSource?.compatibility?.mode || "defense";
}

function selectedTemplateRequest({includeVoice = false} = {}) {
  if (!state.selectedTemplateVersionId) return {};
  const templateOverrides = {};
  const configuredStrategy = state.sessionTemplateSource?.overrides?.question_strategy;
  const selectedStrategy = $("questionStrategy")?.value;
  if (configuredStrategy && selectedStrategy) templateOverrides.question_strategy = selectedStrategy;
  if (includeVoice && $("voiceProvider")?.value) templateOverrides.voice_provider = $("voiceProvider").value;
  return {
    template_version_id: state.selectedTemplateVersionId,
    template_overrides: templateOverrides,
    mode: templateMode(),
  };
}

function expectedSessionTemplateVersionId() {
  if (state.selectedTemplateVersionId) return state.selectedTemplateVersionId;
  return state.publishedTemplates.find(
    (item) => item.slug === "academic.thesis_defense",
  )?.version_id || null;
}

function syncBlueprintTemplateCompatibility() {
  if (!state.blueprintId) return;
  const expectedVersionId = expectedSessionTemplateVersionId();
  const mismatch = Boolean(
    state.blueprintTemplateVersionId
    && expectedVersionId
    && state.blueprintTemplateVersionId !== expectedVersionId
  );
  $("startSession").disabled = mismatch;
  const voiceProvider = selectedVoiceProvider();
  $("startVoice").disabled = mismatch || !(voiceProvider && voiceProvider.ready);
  if (mismatch) {
    setStatus(
      "sessionTemplateHint",
      "场景模板已改变。请先按当前模板重新生成蓝图，再开始文本或语音答辩。",
      "error",
    );
  }
}

function templateTag(value, className = "") {
  return `<span class="template-tag ${className}">${escapeHtml(value || "—")}</span>`;
}

function renderTemplateCatalog() {
  const search = $("templateSearch").value.trim().toLowerCase();
  const category = $("templateCategoryFilter").value;
  const risk = $("templateRiskFilter").value;
  const lifecycle = $("templateLifecycleFilter").value;
  const filtered = state.templates.filter((item) => {
    const haystack = [
      item.slug,
      localized(item.title),
      localized(item.description),
      item.intended_use,
    ].join(" ").toLowerCase();
    return (!search || haystack.includes(search))
      && (!category || item.category === category)
      && (!risk || item.risk_tier === risk)
      && (!lifecycle || item.lifecycle_status === lifecycle);
  });
  $("templateState").textContent = `${filtered.length} / ${state.templates.length} 个模板`;
  $("templateCatalogList").innerHTML = filtered.length
    ? filtered.map((item) => `<button class="template-list-item ${state.selectedTemplate?.id === item.id ? "selected" : ""}" data-template-id="${escapeHtml(item.id)}">
        <strong>${escapeHtml(localized(item.title) || item.slug)}</strong>
        <span class="template-list-meta">
          <span>${escapeHtml(item.slug)}</span>
          <span>v${escapeHtml(item.version)}</span>
          <span>${escapeHtml(item.lifecycle_status)}</span>
        </span>
        <span class="template-list-meta">
          ${templateTag(item.category)}
          ${templateTag(item.risk_tier, `risk-${item.risk_tier}`)}
          ${templateTag(item.trust_level)}
        </span>
      </button>`).join("")
    : "<div class=\"empty compact\">没有匹配的模板。</div>";
  document.querySelectorAll(".template-list-item").forEach((button) => {
    button.onclick = () => selectTemplateIdentity(button.dataset.templateId);
  });
}

function syncSessionTemplateOptions() {
  const previous = $("sessionTemplateSelect").value;
  $("sessionTemplateSelect").innerHTML = [
    "<option value=\"\">兼容模式（论文答辩）</option>",
    ...state.publishedTemplates.map((item) =>
      `<option value="${escapeHtml(item.version_id)}">${escapeHtml(localized(item.title) || item.slug)} · v${escapeHtml(item.version)}</option>`
    ),
  ].join("");
  if ([...$("sessionTemplateSelect").options].some((option) => option.value === previous)) {
    $("sessionTemplateSelect").value = previous;
  }
}

async function loadTemplates() {
  try {
    const [allTemplates, publishedTemplates] = await Promise.all([
      api("/api/templates?include_drafts=true"),
      api("/api/templates"),
    ]);
    state.templates = allTemplates;
    state.publishedTemplates = publishedTemplates;
    syncSessionTemplateOptions();
    renderTemplateCatalog();
    if (!state.selectedTemplate && allTemplates.length) {
      await selectTemplateIdentity(allTemplates[0].id);
    }
  } catch (error) {
    $("templateState").textContent = "加载失败";
    $("templateCatalogList").innerHTML = `<div class="status error">${escapeHtml(error.message)}</div>`;
  }
}

function objectiveRows(source, editable) {
  return (source.objectives || []).map((objective, index) => `<div class="template-row">
    <label>目标标识<input value="${escapeHtml(objective.id)}" disabled /></label>
    <label>中文标题<input data-objective-title="${index}" value="${escapeHtml(localized(objective.title))}" ${editable ? "" : "disabled"} /></label>
    <label>权重<input data-objective-weight="${index}" type="number" min="0" max="1" step="0.01" value="${escapeHtml(objective.weight)}" ${editable ? "" : "disabled"} /></label>
  </div>`).join("");
}

function dimensionRows(source, editable) {
  return (source.assessment_policy?.dimensions || []).map((dimension, index) => `<div class="template-row">
    <label>评分维度<input value="${escapeHtml(dimension.id)}" disabled /></label>
    <label>中文标题<input data-dimension-title="${index}" value="${escapeHtml(localized(dimension.title))}" ${editable ? "" : "disabled"} /></label>
    <label>权重<input data-dimension-weight="${index}" type="number" min="0" max="1" step="0.01" value="${escapeHtml(dimension.weight)}" ${editable ? "" : "disabled"} /></label>
  </div>`).join("");
}

function checkboxGrid(items, selected, attribute, editable) {
  return (items || []).map((item) => `<label class="template-check">
    <input type="checkbox" ${attribute}="${escapeHtml(item)}" ${selected.includes(item) ? "checked" : ""} ${editable ? "" : "disabled"} />
    <span>${escapeHtml(item)}</span>
  </label>`).join("");
}

function templateEditorMarkup(source, editable) {
  const metadata = source.template || {};
  const question = source.question_policy || {};
  const difficulty = question.difficulty || {};
  const assistance = source.assistance_policy || {};
  const conversation = source.conversation_policy || {};
  const assessment = source.assessment_policy || {};
  const report = source.report_policy || {};
  const safety = source.safety_policy || {};
  const knownQuestionTypes = [...new Set(question.allowed_types || [])];
  const knownReportSections = [...new Set(report.sections || [])];
  const knownProhibitedUses = [...new Set(safety.prohibited_uses || [])];
  const disabled = editable ? "" : "disabled";
  return `
    <div class="template-tabs" role="tablist">
      ${[
        ["overview", "目标"],
        ["questions", "提问"],
        ["assistance", "帮助"],
        ["assessment", "评分"],
        ["report", "报告"],
        ["safety", "安全"],
        ["advanced", "高级"],
      ].map(([id, label], index) => `<button class="template-tab ${index === 0 ? "active" : ""}" data-template-tab="${id}" type="button">${label}</button>`).join("")}
    </div>
    <div class="template-editor-panel" data-template-panel="overview">
      <div class="template-form-grid">
        <label>中文名称<input id="templateTitleZh" value="${escapeHtml(metadata.title?.["zh-CN"] || "")}" ${disabled} /></label>
        <label>English title<input id="templateTitleEn" value="${escapeHtml(metadata.title?.en || "")}" ${disabled} /></label>
        <label>中文说明<textarea id="templateDescriptionZh" rows="3" ${disabled}>${escapeHtml(metadata.description?.["zh-CN"] || "")}</textarea></label>
        <label>English description<textarea id="templateDescriptionEn" rows="3" ${disabled}>${escapeHtml(metadata.description?.en || "")}</textarea></label>
      </div>
      <h3>目标与权重</h3>
      <div class="template-rows">${objectiveRows(source, editable)}</div>
    </div>
    <div class="template-editor-panel hidden" data-template-panel="questions">
      <div class="template-form-grid">
        <label>题目数量<input id="templateQuestionLimit" type="number" min="1" max="20" value="${escapeHtml(question.question_limit ?? 6)}" ${disabled} /></label>
        <label>选题策略<select id="templateSelectionStrategy" ${disabled}><option value="fixed" ${question.selection_strategy === "fixed" ? "selected" : ""}>固定顺序</option><option value="adaptive" ${question.selection_strategy === "adaptive" ? "selected" : ""}>自适应</option></select></label>
        <label>最低难度<input id="templateDifficultyMin" type="number" min="1" max="5" value="${escapeHtml(difficulty.minimum ?? 1)}" ${disabled} /></label>
        <label>初始难度<input id="templateDifficultyInitial" type="number" min="1" max="5" value="${escapeHtml(difficulty.initial ?? 3)}" ${disabled} /></label>
        <label>最高难度<input id="templateDifficultyMax" type="number" min="1" max="5" value="${escapeHtml(difficulty.maximum ?? 5)}" ${disabled} /></label>
        <label>每题最多追问<input id="templateMaxFollowups" type="number" min="0" max="5" value="${escapeHtml(conversation.max_followups_per_question ?? 2)}" ${disabled} /></label>
      </div>
      <h3>允许的问题类型</h3>
      <div class="template-check-grid">${checkboxGrid(knownQuestionTypes, question.allowed_types || [], "data-question-type", editable)}</div>
    </div>
    <div class="template-editor-panel hidden" data-template-panel="assistance">
      <div class="template-check-grid">
        <label class="template-check"><input id="templateHintsAllowed" type="checkbox" ${assistance.hints?.allowed ? "checked" : ""} ${disabled} /><span>允许提示</span></label>
        <label class="template-check"><input id="templateCorrectionsAllowed" type="checkbox" ${assistance.corrections?.allowed ? "checked" : ""} ${disabled} /><span>允许纠正</span></label>
        <label class="template-check"><input id="templateDisclosureAllowed" type="checkbox" ${assistance.answer_disclosure?.allowed ? "checked" : ""} ${disabled} /><span>允许直接给出答案</span></label>
        <label class="template-check"><input id="templateInterruptionEnabled" type="checkbox" ${conversation.interruption?.enabled ? "checked" : ""} ${disabled} /><span>允许主动打断</span></label>
      </div>
      <div class="template-form-grid">
        <label>每题最多提示<input id="templateMaxHints" type="number" min="0" max="5" value="${escapeHtml(assistance.hints?.maximum_per_question ?? 0)}" ${disabled} /></label>
        <label>纠正时机<select id="templateCorrectionTiming" ${disabled}><option value="never" ${assistance.corrections?.timing === "never" ? "selected" : ""}>不纠正</option><option value="after_independent_attempt" ${assistance.corrections?.timing === "after_independent_attempt" ? "selected" : ""}>独立作答后</option><option value="after_followups" ${assistance.corrections?.timing === "after_followups" ? "selected" : ""}>追问后</option><option value="session_end" ${assistance.corrections?.timing === "session_end" ? "selected" : ""}>会话结束</option></select></label>
      </div>
    </div>
    <div class="template-editor-panel hidden" data-template-panel="assessment">
      <div class="template-form-grid">
        <label>汇总方式<select id="templateAggregate" ${disabled}><option value="weighted_dimensions" ${assessment.aggregate === "weighted_dimensions" ? "selected" : ""}>加权总分</option><option value="no_total" ${assessment.aggregate === "no_total" ? "selected" : ""}>不显示总分</option></select></label>
        <label>辅助表现<select id="templateAssistedPerformance" ${disabled}><option value="ignore" ${assessment.assisted_performance === "ignore" ? "selected" : ""}>忽略</option><option value="report_separately" ${assessment.assisted_performance === "report_separately" ? "selected" : ""}>单独报告</option><option value="blend_with_independent" ${assessment.assisted_performance === "blend_with_independent" ? "selected" : ""}>与独立表现合并</option></select></label>
      </div>
      <div class="template-rows">${dimensionRows(source, editable)}</div>
    </div>
    <div class="template-editor-panel hidden" data-template-panel="report">
      <label class="template-check"><input id="templateShowTotal" type="checkbox" ${report.show_total_score ? "checked" : ""} ${disabled} /><span>报告显示总分</span></label>
      <label>免责声明标识<input id="templateDisclaimer" value="${escapeHtml(report.required_disclaimer || "")}" ${disabled} /></label>
      <h3>报告章节</h3>
      <div class="template-check-grid">${checkboxGrid(knownReportSections, report.sections || [], "data-report-section", editable)}</div>
    </div>
    <div class="template-editor-panel hidden" data-template-panel="safety">
      <label class="template-check"><input id="templateHumanReview" type="checkbox" ${safety.human_review_required ? "checked" : ""} ${disabled} /><span>要求人工复核</span></label>
      <p>受保护属性推断固定为禁止。高风险用途只能收紧，不能通过编辑器解除平台边界。</p>
      <div class="template-check-grid">${checkboxGrid(knownProhibitedUses, safety.prohibited_uses || [], "data-prohibited-use", editable)}</div>
    </div>
    <div class="template-editor-panel hidden" data-template-panel="advanced">
      <label>原始 JSON<textarea id="templateRawSource" class="template-raw" ${disabled}>${escapeHtml(JSON.stringify(source, null, 2))}</textarea></label>
      <p>高级编辑仍受结构、语义、能力和安全校验约束。</p>
    </div>`;
}

function bindTemplateTabs() {
  document.querySelectorAll(".template-tab").forEach((button) => {
    button.onclick = () => {
      document.querySelectorAll(".template-tab").forEach((item) => item.classList.toggle("active", item === button));
      document.querySelectorAll("[data-template-panel]").forEach((panel) => {
        panel.classList.toggle("hidden", panel.dataset.templatePanel !== button.dataset.templateTab);
      });
    };
  });
}

function templateVersionOption(version) {
  return `<option value="${escapeHtml(version.id)}">${escapeHtml(version.semantic_version)} · ${escapeHtml(version.status)}</option>`;
}

function renderEffectivePreview(payload) {
  const effective = payload.effective_settings;
  const conversation = effective.conversation || {};
  const question = effective.question_selection || {};
  $("templateEffectivePreview").innerHTML = `
    <div><span>有效指纹</span><strong>${escapeHtml(payload.fingerprint.slice(0, 22))}…</strong></div>
    <div><span>选题策略</span><strong>${escapeHtml(question.strategy)}</strong></div>
    <div><span>题目 / 追问</span><strong>${escapeHtml(question.question_limit)} / ${escapeHtml(conversation.max_followups_per_question)}</strong></div>
    <div><span>评分汇总</span><strong>${escapeHtml(effective.assessment?.aggregate)}</strong></div>`;
}

function renderTemplateDetail() {
  const template = state.selectedTemplate;
  const version = state.selectedTemplateVersion;
  const source = state.selectedTemplateSource;
  if (!template || !version || !source) return;
  const metadata = source.template || {};
  const editable = template.owner_scope === "local" && version.status === "draft";
  const canBind = version.status === "published";
  const canCandidate = editable;
  const canReturnDraft = template.owner_scope === "local" && version.status === "candidate";
  const canPublish = canReturnDraft
    && version.evaluation_summary?.status === "passed"
    && Number(version.evaluation_summary?.fixture_count || 0) > 0;
  const canDeprecate = template.owner_scope === "local" && version.status === "published";
  const cloneSlug = `local.${template.slug.split(".").slice(-1)[0]}_copy`;
  $("templateDetail").innerHTML = `
    <div class="template-detail-head">
      <div>
        <h3>${escapeHtml(localized(metadata.title) || template.slug)}</h3>
        <p>${escapeHtml(localized(metadata.description))}</p>
        <div class="template-meta-row">
          ${templateTag(template.category)}
          ${templateTag(metadata.risk_tier, `risk-${metadata.risk_tier}`)}
          ${templateTag(metadata.intended_use)}
          ${templateTag(metadata.trust_level)}
          ${templateTag(version.status)}
        </div>
      </div>
      <label class="template-version-select">版本<select id="templateVersionSelect">${template.versions.map(templateVersionOption).join("")}</select></label>
    </div>
    <div class="template-actions">
      <button id="useTemplate" ${canBind ? "" : "disabled"}>用于下一次会话</button>
      <button id="bindProjectTemplate" class="secondary-button" ${canBind ? "" : "disabled"}>设为项目默认</button>
      <button id="previewTemplate" class="secondary-button">预览有效策略</button>
      <a class="button-link" href="/api/template-versions/${escapeHtml(version.id)}/export?format=yaml">导出 YAML</a>
      <button id="validateTemplate" class="secondary-button">校验</button>
      <button id="compileTemplate" class="secondary-button">编译</button>
      <button id="saveTemplate" ${editable ? "" : "disabled"}>保存草稿</button>
      <button id="candidateTemplate" ${canCandidate ? "" : "disabled"}>提交候选</button>
      <button id="returnDraftTemplate" class="secondary-button" ${canReturnDraft ? "" : "disabled"}>退回草稿</button>
      <button id="publishTemplate" ${canPublish ? "" : "disabled"} title="${canPublish ? "" : "发布需要通过行为评测"}">发布</button>
      <button id="deprecateTemplate" class="danger-button" ${canDeprecate ? "" : "disabled"}>弃用</button>
    </div>
    <div class="template-form-grid">
      <label>本地副本标识<input id="templateCloneSlug" value="${escapeHtml(cloneSlug)}" /></label>
      <label>副本版本<input id="templateCloneVersion" value="0.1.0" /></label>
    </div>
    <div class="template-actions"><button id="cloneTemplate" class="secondary-button">创建本地副本</button></div>
    <div id="templateActionStatus" class="status">${editable ? "这是可编辑的本地草稿。" : "此版本不可直接修改；请先创建本地副本。"}</div>
    <div id="templateEffectivePreview" class="template-preview">
      <div><span>模板标识</span><strong>${escapeHtml(template.slug)}</strong></div>
      <div><span>版本</span><strong>${escapeHtml(version.semantic_version)}</strong></div>
      <div><span>兼容模式</span><strong>${escapeHtml(source.compatibility?.mode || "—")}</strong></div>
      <div><span>指纹</span><strong>${escapeHtml((version.fingerprint || "未编译").slice(0, 22))}</strong></div>
    </div>
    <div class="template-form-grid">
      <label>比较版本<select id="templateDiffTarget">${template.versions.filter((item) => item.id !== version.id).map(templateVersionOption).join("") || "<option value=\"\">没有其他版本</option>"}</select></label>
      <div class="template-actions"><button id="compareTemplate" class="secondary-button" ${template.versions.length > 1 ? "" : "disabled"}>比较差异</button></div>
    </div>
    <div id="templateDiff" class="template-diff hidden"></div>
    ${templateEditorMarkup(source, editable)}`;
  $("templateVersionSelect").value = version.id;
  $("templateVersionSelect").onchange = () => selectTemplateVersion($("templateVersionSelect").value);
  bindTemplateTabs();
  bindTemplateActions();
  state.templateRawDirty = false;
  if ($("templateRawSource")) $("templateRawSource").oninput = () => { state.templateRawDirty = true; };
}

async function selectTemplateIdentity(templateId, preferredVersionId = null) {
  try {
    const detail = await api(`/api/templates/${templateId}`);
    state.selectedTemplate = detail;
    const selected = detail.versions.find((item) => item.id === preferredVersionId)
      || detail.versions[0];
    await selectTemplateVersion(selected.id, false);
    renderTemplateCatalog();
  } catch (error) {
    $("templateDetail").innerHTML = `<div class="status error">${escapeHtml(error.message)}</div>`;
  }
}

async function selectTemplateVersion(versionId, rerenderCatalog = true) {
  const version = await api(`/api/template-versions/${versionId}`);
  state.selectedTemplateVersion = version;
  state.selectedTemplateSource = structuredClone(version.source);
  if (rerenderCatalog) renderTemplateCatalog();
  renderTemplateDetail();
}

function collectTemplateSource() {
  if (state.templateRawDirty) {
    try {
      return JSON.parse($("templateRawSource").value);
    } catch (error) {
      throw new Error(`原始 JSON 无法解析：${error.message}`);
    }
  }
  const source = structuredClone(state.selectedTemplateSource);
  source.template.title["zh-CN"] = $("templateTitleZh").value.trim();
  source.template.title.en = $("templateTitleEn").value.trim();
  source.template.description["zh-CN"] = $("templateDescriptionZh").value.trim();
  source.template.description.en = $("templateDescriptionEn").value.trim();
  source.objectives.forEach((objective, index) => {
    objective.title["zh-CN"] = document.querySelector(`[data-objective-title="${index}"]`).value.trim();
    objective.weight = Number(document.querySelector(`[data-objective-weight="${index}"]`).value);
  });
  source.question_policy.question_limit = Number($("templateQuestionLimit").value);
  source.question_policy.selection_strategy = $("templateSelectionStrategy").value;
  source.question_policy.difficulty.minimum = Number($("templateDifficultyMin").value);
  source.question_policy.difficulty.initial = Number($("templateDifficultyInitial").value);
  source.question_policy.difficulty.maximum = Number($("templateDifficultyMax").value);
  source.question_policy.allowed_types = [...document.querySelectorAll("[data-question-type]:checked")]
    .map((item) => item.dataset.questionType);
  source.conversation_policy.max_followups_per_question = Number($("templateMaxFollowups").value);
  source.assistance_policy.hints.allowed = $("templateHintsAllowed").checked;
  source.assistance_policy.hints.maximum_per_question = Number($("templateMaxHints").value);
  source.assistance_policy.corrections.allowed = $("templateCorrectionsAllowed").checked;
  source.assistance_policy.corrections.timing = $("templateCorrectionTiming").value;
  source.assistance_policy.answer_disclosure.allowed = $("templateDisclosureAllowed").checked;
  source.conversation_policy.interruption.enabled = $("templateInterruptionEnabled").checked;
  source.assessment_policy.aggregate = $("templateAggregate").value;
  source.assessment_policy.assisted_performance = $("templateAssistedPerformance").value;
  source.assessment_policy.dimensions.forEach((dimension, index) => {
    dimension.title["zh-CN"] = document.querySelector(`[data-dimension-title="${index}"]`).value.trim();
    dimension.weight = Number(document.querySelector(`[data-dimension-weight="${index}"]`).value);
  });
  source.report_policy.show_total_score = $("templateShowTotal").checked;
  source.report_policy.required_disclaimer = $("templateDisclaimer").value.trim();
  source.report_policy.sections = [...document.querySelectorAll("[data-report-section]:checked")]
    .map((item) => item.dataset.reportSection);
  source.safety_policy.human_review_required = $("templateHumanReview").checked;
  source.safety_policy.prohibited_uses = [...document.querySelectorAll("[data-prohibited-use]:checked")]
    .map((item) => item.dataset.prohibitedUse);
  return source;
}

async function templateTransition(status) {
  if (["published", "deprecated"].includes(status)
      && !window.confirm(`确认将该模板标记为“${status}”？`)) return;
  const version = await api(`/api/template-versions/${state.selectedTemplateVersion.id}/status`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({status}),
  });
  setStatus("templateActionStatus", `模板状态已更新为 ${version.status}`, "success");
  await loadTemplates();
  await selectTemplateIdentity(state.selectedTemplate.id, version.id);
}

function renderTemplateDiff(payload) {
  const target = $("templateDiff");
  target.classList.remove("hidden");
  target.innerHTML = payload.groups.length
    ? payload.groups.map((group) => `<details class="template-diff-group" open>
        <summary>${escapeHtml(group.id)} · ${group.change_count} 项</summary>
        ${group.changes.map((change) => `<div class="template-diff-change">${escapeHtml(change.kind)} ${escapeHtml(change.path)}</div>`).join("")}
      </details>`).join("")
    : "<div class=\"template-empty-note\">两个版本没有语义差异。</div>";
}

function bindTemplateActions() {
  $("useTemplate").onclick = async () => {
    state.selectedTemplateVersionId = state.selectedTemplateVersion.id;
    state.sessionTemplateSource = structuredClone(state.selectedTemplateSource);
    state.sessionTemplateLabel = localized(state.selectedTemplateSource.template.title);
    $("sessionTemplateSelect").value = state.selectedTemplateVersionId;
    $("questionStrategy").value = state.selectedTemplateSource.question_policy?.selection_strategy || "fixed";
    setStatus("sessionTemplateHint", `${localized(state.selectedTemplateSource.template.title)} v${state.selectedTemplateVersion.semantic_version} 将用于下一次蓝图和会话。`, "success");
  };
  $("bindProjectTemplate").onclick = async () => {
    if (!state.projectId) return setStatus("templateActionStatus", "请先创建项目。", "error");
    await api(`/api/projects/${state.projectId}/template-binding`, {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({template_version_id: state.selectedTemplateVersion.id, default_overrides: {}}),
    });
    setStatus("templateActionStatus", "已设为当前项目的新会话默认模板。", "success");
  };
  $("previewTemplate").onclick = async () => {
    try {
      const preview = await api(`/api/template-versions/${state.selectedTemplateVersion.id}/preview`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({overrides: {}, fixture: "partial_answer"}),
      });
      renderEffectivePreview(preview);
      setStatus("templateActionStatus", "有效策略预览已更新。", "success");
    } catch (error) { setStatus("templateActionStatus", error.message, "error"); }
  };
  $("validateTemplate").onclick = async () => {
    try {
      const result = await api(`/api/template-versions/${state.selectedTemplateVersion.id}/validate`, {method: "POST"});
      const errors = (result.issues || []).filter((item) => item.severity === "error");
      setStatus("templateActionStatus", errors.length ? `校验发现 ${errors.length} 个错误。` : "结构、语义和能力校验通过。", errors.length ? "error" : "success");
    } catch (error) { setStatus("templateActionStatus", error.message, "error"); }
  };
  $("compileTemplate").onclick = async () => {
    try {
      const result = await api(`/api/template-versions/${state.selectedTemplateVersion.id}/compile`, {method: "POST"});
      setStatus("templateActionStatus", `编译通过：${result.fingerprint.slice(0, 24)}…`, "success");
      await selectTemplateVersion(state.selectedTemplateVersion.id);
    } catch (error) { setStatus("templateActionStatus", error.message, "error"); }
  };
  $("saveTemplate").onclick = async () => {
    try {
      const source = collectTemplateSource();
      const result = await api(`/api/template-versions/${state.selectedTemplateVersion.id}`, {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({source}),
      });
      await loadTemplates();
      await selectTemplateIdentity(state.selectedTemplate.id, result.id);
      setStatus("templateActionStatus", "草稿已保存并重新校验。", "success");
    } catch (error) { setStatus("templateActionStatus", error.message, "error"); }
  };
  $("cloneTemplate").onclick = async () => {
    try {
      const slug = $("templateCloneSlug").value.trim();
      const semanticVersion = $("templateCloneVersion").value.trim();
      let result;
      if (state.selectedTemplate.owner_scope === "local") {
        result = await api(`/api/template-versions/${state.selectedTemplateVersion.id}/clone`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({semantic_version: semanticVersion}),
        });
        await loadTemplates();
        await selectTemplateIdentity(state.selectedTemplate.id, result.id);
      } else {
        result = await api("/api/templates/import", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            document: state.selectedTemplateSource,
            target_slug: slug,
            semantic_version: semanticVersion,
          }),
        });
        await loadTemplates();
        await selectTemplateIdentity(result.template.id, result.version.id);
      }
      setStatus("templateActionStatus", "本地草稿副本已创建。", "success");
    } catch (error) { setStatus("templateActionStatus", error.message, "error"); }
  };
  $("candidateTemplate").onclick = () => templateTransition("candidate").catch((error) => setStatus("templateActionStatus", error.message, "error"));
  $("returnDraftTemplate").onclick = () => templateTransition("draft").catch((error) => setStatus("templateActionStatus", error.message, "error"));
  $("publishTemplate").onclick = () => templateTransition("published").catch((error) => setStatus("templateActionStatus", error.message, "error"));
  $("deprecateTemplate").onclick = () => templateTransition("deprecated").catch((error) => setStatus("templateActionStatus", error.message, "error"));
  $("compareTemplate").onclick = async () => {
    try {
      const target = $("templateDiffTarget").value;
      const diff = await api(`/api/template-versions/${state.selectedTemplateVersion.id}/diff/${target}`);
      renderTemplateDiff(diff);
    } catch (error) { setStatus("templateActionStatus", error.message, "error"); }
  };
}

function selectedVoiceProvider() {
  const providers = state.voiceConfig && state.voiceConfig.providers ? state.voiceConfig.providers : [];
  return providers.find((item) => item.id === $("voiceProvider").value) || providers[0] || null;
}

async function getUserMediaWithTimeout(constraints, timeoutMs = 20000) {
  let expired = false;
  let timeoutId;
  const mediaPromise = navigator.mediaDevices.getUserMedia(constraints).then((stream) => {
    if (expired) {
      stream.getTracks().forEach((track) => track.stop());
      throw new Error("麦克风授权或设备启动超时。请检查浏览器权限和系统输入设备后重试。");
    }
    return stream;
  });
  try {
    return await Promise.race([
      mediaPromise,
      new Promise((_, reject) => {
        timeoutId = setTimeout(() => {
          expired = true;
          reject(new Error("麦克风授权或设备启动超时。请检查浏览器权限和系统输入设备后重试。"));
        }, timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timeoutId);
  }
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
    const [health, providers, voiceConfig] = await Promise.all([
      api("/health", {organizationScoped: false}),
      api("/api/providers"),
      api("/api/voice/config"),
    ]);
    state.voiceConfig = voiceConfig;
    state.providers = providers;
    $("providerBadge").textContent = `${health.provider} · ${health.model} · v${health.version}`;
    if (!health.provider_ready) $("providerBadge").textContent += " · 未配置";
    const readyProviders = providers.filter((provider) => provider.ready);
    const configuredProfile = `${health.provider}:${health.model}`;
    const preferredProvider = readyProviders.find((provider) => provider.id === configuredProfile)
      || readyProviders.find((provider) => provider.provider === health.provider)
      || readyProviders.find((provider) => provider.provider === "ollama")
      || readyProviders.find((provider) => provider.provider !== "mock")
      || readyProviders[0];
    const modelList = $("modelProfiles");
    modelList.innerHTML = providers.map((provider) => {
      const checked = provider.id === preferredProvider?.id ? "checked" : "";
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
    const readyProviderOptions = readyProviders.map((provider) =>
      `<option value="${escapeHtml(provider.id)}">${escapeHtml(provider.label)}</option>`
    ).join("");
    $("blueprintProfile").innerHTML = readyProviderOptions;
    $("textProfile").innerHTML = readyProviderOptions;
    const visionProviders = readyProviders.filter((provider) => provider.supports_vision);
    $("visualProfile").innerHTML = visionProviders.map((provider) =>
      `<option value="${escapeHtml(provider.id)}">${escapeHtml(provider.label)}</option>`
    ).join("");
    if (preferredProvider) {
      $("blueprintProfile").value = preferredProvider.id;
      $("textProfile").value = preferredProvider.id;
    }
    const preferredVision = visionProviders.find((provider) => provider.id === "qwen:qwen3-vl-plus")
      || visionProviders.find((provider) => provider.provider !== "mock")
      || visionProviders[0];
    if (preferredVision) $("visualProfile").value = preferredVision.id;
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
  const requestKey = state.blueprintRequestKey
    || (globalThis.crypto?.randomUUID?.() || `blueprint-${Date.now()}-${Math.random()}`);
  state.blueprintRequestKey = requestKey;
  $("generateBlueprint").disabled = true;
  $("cancelBlueprint").classList.remove("hidden");
  $("blueprintProgress").classList.remove("hidden");
  setStatus("blueprintStatus", `已提交给 ${profile}，可以继续留在页面查看进度。`);
  try {
    const queued = await api(`/api/projects/${state.projectId}/blueprints/async`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": requestKey,
      },
      body: JSON.stringify({
        document_id: state.documentId,
        profile,
        ...selectedTemplateRequest(),
      }),
    });
    state.blueprintJobId = queued.id;
    const job = await pollBlueprintJob(queued.id);
    const blueprint = job.result?.blueprint;
    if (!blueprint) throw new Error("任务已完成，但没有返回蓝图结果");
    state.blueprintId = blueprint.id;
    state.blueprintTemplateVersionId =
      blueprint.template_plan?.template_version_id
      || blueprint.data?.template_plan?.template_version_id
      || null;
    if ([...$("textProfile").options].some((option) => option.value === profile)) {
      $("textProfile").value = profile;
    }
    syncBlueprintTemplateCompatibility();
    setStatus("blueprintStatus", `蓝图 v${blueprint.version} 已生成：${blueprint.provider} · ${blueprint.model}，共 ${blueprint.data.questions.length} 个问题`, "success");
    const preview = $("blueprintPreview");
    preview.classList.remove("hidden");
    preview.innerHTML = `<strong>${escapeHtml(blueprint.data.title)}</strong><p>${escapeHtml(blueprint.data.summary)}</p><ol>${blueprint.data.questions.map((question) => `<li>${escapeHtml(question.text)}</li>`).join("")}</ol>`;
    state.blueprintRequestKey = null;
  } catch (error) {
    setStatus("blueprintStatus", error.message, "error");
    if (/取消|失败|dead.?letter/i.test(error.message)) state.blueprintRequestKey = null;
  } finally {
    state.blueprintJobId = null;
    $("generateBlueprint").disabled = false;
    $("cancelBlueprint").classList.add("hidden");
  }
};

async function pollBlueprintJob(jobId) {
  const startedAt = Date.now();
  for (let attempt = 0; attempt < 450; attempt += 1) {
    const job = await api(`/api/jobs/${jobId}`);
    const percent = Math.max(0, Math.min(100, Math.round(Number(job.progress || 0) * 100)));
    const elapsed = Math.round((Date.now() - startedAt) / 1000);
    $("blueprintProgress").querySelector("span").style.width = `${percent}%`;
    $("blueprintProgress").querySelector("small").textContent =
      `${job.message || job.status} · ${percent}% · 已用时 ${elapsed} 秒`;
    if (job.status === "completed") return job;
    if (job.status === "cancelled") throw new Error("蓝图生成已取消");
    if (job.status === "failed") throw new Error(job.error || "蓝图生成失败");
    if (job.status === "dead_letter") {
      throw new Error(job.error || "蓝图生成多次重试后仍失败");
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error("蓝图仍在后台运行，请稍后从任务列表检查状态");
}

$("cancelBlueprint").onclick = async () => {
  if (!state.blueprintJobId) return;
  $("cancelBlueprint").disabled = true;
  try {
    await api(`/api/jobs/${state.blueprintJobId}/cancel`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({reason: "User cancelled blueprint generation"}),
    });
    setStatus("blueprintStatus", "已请求取消；若模型调用已经发出，系统会丢弃其结果。");
  } catch (error) {
    setStatus("blueprintStatus", error.message, "error");
  } finally {
    $("cancelBlueprint").disabled = false;
  }
};

function renderQuality(dataset) {
  const quality = dataset.quality_metrics;
  $("datasetState").textContent = `${dataset.status} · v${dataset.version}`;
  $("qualityMetrics").innerHTML = [
    ["题目数", quality.case_count],
    ["材料忠实率", `${Math.round(quality.grounded_rate * 100)}%`],
    ["标注完整率", `${Math.round(quality.annotation_completeness * 100)}%`],
    ["文本卫生", `${Math.round(Number(quality.text_hygiene_rate ?? 1) * 100)}%`],
    ["类型覆盖", quality.type_coverage],
    ["AI Panel", quality.mean_ai_panel_score ?? "—"],
    ["估算费用", `$${Number(quality.total_estimated_cost_usd || 0).toFixed(4)}`],
  ].map(([label, value]) => `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
  $("freezeDataset").disabled = !quality.release_ready;
  $("freezeDataset").title = quality.release_ready
    ? "冻结为稳定回归基准"
    : "质量门禁未通过，不能冻结";
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
    $("freezeDataset").disabled = !dataset.quality_metrics.release_ready;
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
    const sessionPayload = {
      project_id: state.projectId,
      blueprint_id: state.blueprintId,
      profile,
      learner_subject_key: `browser-${state.projectId}`,
      ...selectedTemplateRequest(),
    };
    if (!state.selectedTemplateVersionId) {
      Object.assign(sessionPayload, {
        question_limit: 6,
        max_followups_per_question: 2,
        question_strategy: $("questionStrategy").value,
      });
    }
    const session = await api("/api/sessions", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(sessionPayload),
    });
    state.sessionId = session.id;
    state.learnerSubjectId = session.learner_subject_id;
    $("enableMemory").disabled = false;
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
      $("answerHint").textContent = "答辩已完成，报告已经生成。";
      await showReport();
      if (state.identityId && result.retest_item) await refreshMemory();
    } else {
      $("sendAnswer").disabled = false;
      $("answerInput").disabled = false;
      $("answerInput").focus();
      const reasons = result.decision.selection?.reason_codes || [];
      $("answerHint").textContent = result.decision.action === "ASK_FOLLOWUP"
        ? "当前为追问，请直接回应追问。"
        : (reasons.length ? `选题依据：${reasons.join(" · ")}` : "一次只回答当前问题。");
    }
  } catch (error) {
    window.alert(error.message);
    $("sendAnswer").disabled = false;
    $("answerInput").disabled = false;
  }
};

async function showReport() {
  const report = await api(`/api/sessions/${state.sessionId}/report`);
  const assessmentSummary = report.assessment_summary || {};
  const trajectories = report.question_trajectories || [];
  const scoreMarkup = report.show_total_score === false
    ? `<div class="score">—</div><div><strong>本模板不生成总分</strong><p>请查看分维度与目标证据</p></div>`
    : `<div class="score">${escapeHtml(report.overall_score)}<small>/${escapeHtml(report.max_score || 5)}</small></div><div><strong>风险等级：${escapeHtml(report.risk_level)}</strong><p>已评估 ${report.questions_answered} 次回答</p></div>`;
  $("reportPanel").classList.remove("hidden");
  $("reportContent").innerHTML = `
    <div class="score-card">${scoreMarkup}</div>
    <div class="report-block"><h3>回答轨迹</h3><p>独立回答均分 ${escapeHtml(assessmentSummary.independent_average ?? "—")} · 追问后均分 ${escapeHtml(assessmentSummary.assisted_average ?? "—")} · 平均提升 ${escapeHtml(assessmentSummary.average_learning_gain ?? "—")}</p><ul>${trajectories.map((item) => `<li><strong>${escapeHtml(item.question_id)}</strong>：${escapeHtml(item.independent_score)} → ${escapeHtml(item.final_assisted_score)}，追问 ${escapeHtml(item.followup_count)} 次，提升 ${escapeHtml(item.learning_gain)}</li>`).join("") || "<li>暂无回答轨迹</li>"}</ul></div>
    <div class="report-grid">
      <div class="report-block"><h3>目标表现</h3><ul>${(report.objective_scores || []).map((item) => `<li><strong>${escapeHtml(item.title || item.id)}</strong>：${item.score == null ? "未考察" : `${escapeHtml(item.score)}/${escapeHtml(report.max_score || 5)}`} · 证据 ${escapeHtml(item.evidence_count || 0)} 条</li>`).join("") || "<li>当前会话未绑定目标评分</li>"}</ul></div>
      <div class="report-block"><h3>优先薄弱点</h3><ul>${list(report.priority_weaknesses, "暂未识别明显薄弱点")}</ul></div>
      <div class="report-block"><h3>建议动作</h3><ul>${list(report.recommended_actions)}</ul></div>
      <div class="report-block"><h3>高分证据</h3><ul>${list(report.strengths, "尚无达到高分阈值的回答")}</ul></div>
      <div class="report-block"><h3>分类型表现</h3><ul>${Object.entries(report.dimension_summary).map(([key, value]) => `<li>${escapeHtml(key)}：${value}/5</li>`).join("") || "<li>暂无</li>"}</ul></div>
      <div class="report-block"><h3>知识地图</h3><ul>${(report.knowledge_map || []).map((item) => `<li><strong>${escapeHtml(item.name)}</strong>：掌握度 ${Math.round(item.mastery * 100)}% · 置信度 ${Math.round(item.confidence * 100)}% · ${escapeHtml(item.status)}</li>`).join("") || "<li>尚未形成概念证据</li>"}</ul></div>
      <div class="report-block"><h3>改进路径</h3><ul>${list(report.improvement_path, "完成更多回答后生成改进路径")}</ul></div>
    </div>
    <div class="report-block"><h3>问题与原始证据</h3><div class="evidence-report-grid">${(report.evidence || []).map((item) => `<article>
      ${item.page_preview_url ? `<a href="${item.page_preview_url}" target="_blank"><img src="${item.page_preview_url}" alt="第 ${item.source_page || "?"} 页证据" /></a>` : ""}
      <strong>${escapeHtml(item.question_id || "问题")}</strong><small>第 ${escapeHtml(item.source_page || "?")} 页 · 得分 ${escapeHtml(item.score)}</small>
      <p>${escapeHtml(item.source_excerpt || "未记录来源片段")}</p>
    </article>`).join("") || "<p>暂无页面证据。</p>"}</div></div>
    <p>${escapeHtml(report.disclaimer)}</p>`;
  $("reportPanel").scrollIntoView({behavior: "smooth"});
}

function syncPreferenceValues() {
  const options = preferenceOptions[$("preferenceKey").value] || [];
  $("preferenceValue").innerHTML = options
    .map(([value, label]) => `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`)
    .join("");
}

function browserIdentityReference() {
  let reference = localStorage.getItem("ai-examiner-browser-reference");
  if (!reference) {
    reference = `browser-${crypto.randomUUID ? crypto.randomUUID() : Date.now()}`;
    localStorage.setItem("ai-examiner-browser-reference", reference);
  }
  return reference;
}

async function enableMemory() {
  if (!state.learnerSubjectId) {
    throw new Error("请先开始一场文本或语音答辩，再启用长期记忆");
  }
  const identity = await api("/api/learner-identities", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      external_subject_ref: browserIdentityReference(),
      display_name: $("memoryDisplayName").value.trim() || "我的学习档案",
      memory_enabled: true,
      memory_scope: "linked_projects",
    }),
  });
  state.identityId = identity.id;
  localStorage.setItem("ai-examiner-identity-id", identity.id);
  await api(`/api/learner-identities/${identity.id}/memory-settings`, {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      memory_enabled: true,
      memory_scope: "linked_projects",
      retest_planning_enabled: true,
    }),
  });
  await api(`/api/learner-identities/${identity.id}/links`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({learner_subject_id: state.learnerSubjectId, provenance: "explicit"}),
  });
  ["importMemory", "refreshMemory", "exportMemory", "deleteMemory", "savePreference", "planRetest"]
    .forEach((id) => { $(id).disabled = false; });
  $("memoryState").textContent = "已启用";
  await refreshMemory();
}

function renderMemoryCenter(center) {
  const states = center.concept_states || [];
  $("conceptStates").innerHTML = states.map((item) => `
    <div class="memory-row">
      <div class="memory-row-head"><strong>${escapeHtml(item.concept_title || item.concept_id)}</strong><small>${item.evidence_count} 条证据</small></div>
      <div class="memory-meter" title="已观察 ${Math.round(item.observed_mastery * 100)}%，时间推算 ${Math.round(item.predicted_retention * 100)}%"><span style="width:${Math.round(item.observed_mastery * 100)}%"></span><span class="predicted" style="width:${Math.round(item.predicted_retention * 100)}%"></span></div>
      <small>已观察 ${Math.round(item.observed_mastery * 100)}% · 时间推算 ${Math.round(item.predicted_retention * 100)}% · 置信度 ${Math.round(item.prediction_confidence * 100)}%</small>
      <small>${item.active_misconceptions.length ? `待纠正：${escapeHtml(item.active_misconceptions.join("；"))}` : "未记录活跃误区"}</small>
    </div>`).join("") || `<div class="empty compact">尚无结构化学习证据。</div>`;

  const preferences = center.preferences || [];
  $("preferenceList").innerHTML = preferences.map((item) => `
    <div class="memory-row">
      <div class="memory-row-head"><strong>${escapeHtml(item.preference_key)}</strong><small>${escapeHtml(item.status)}</small></div>
      <small>${escapeHtml(item.value)} · ${item.source === "explicit" ? "用户明确设置" : "系统提议"}</small>
      ${item.status === "proposed" ? `<div class="memory-actions"><button data-preference-action="confirm" data-preference-id="${item.id}">确认</button><button class="danger-button" data-preference-action="reject" data-preference-id="${item.id}">拒绝</button></div>` : ""}
    </div>`).join("") || `<div class="empty compact">尚无偏好。推断偏好必须经您确认后才会生效。</div>`;

  const items = (center.retest_plans || []).flatMap((plan) => plan.items || []);
  $("retestList").innerHTML = items.map((item) => `
    <div class="memory-row">
      <div class="memory-row-head"><strong>${escapeHtml(item.concept_title || item.concept_id)}</strong><small>${escapeHtml(item.status)}</small></div>
      <small>原因：${escapeHtml(item.reason_code)} · 建议时间 ${new Date(item.due_at).toLocaleDateString()} · 预计保留度 ${Math.round(item.predicted_retention * 100)}%</small>
      <div class="memory-actions">
        ${item.status === "proposed" ? `<button data-retest-action="accept" data-retest-id="${item.id}">接受</button><button class="danger-button" data-retest-action="dismiss" data-retest-id="${item.id}">稍后再说</button>` : ""}
        ${item.status === "accepted" ? `<button data-retest-action="start" data-retest-id="${item.id}">开始复测</button>` : ""}
      </div>
    </div>`).join("") || `<div class="empty compact">暂无复测建议。</div>`;

  document.querySelectorAll("[data-preference-action]").forEach((button) => {
    button.onclick = () => actOnPreference(button.dataset.preferenceId, button.dataset.preferenceAction);
  });
  document.querySelectorAll("[data-retest-action]").forEach((button) => {
    button.onclick = () => actOnRetest(button.dataset.retestId, button.dataset.retestAction);
  });
}

async function refreshMemory() {
  if (!state.identityId) return;
  const center = await api(`/api/learner-identities/${state.identityId}/memory-center`);
  renderMemoryCenter(center);
  $("memoryState").textContent = center.identity.memory_enabled ? "已启用" : "已关闭";
  setStatus("memoryStatus", `已加载 ${center.concept_states.length} 个知识状态。`, "success");
}

async function actOnPreference(preferenceId, action) {
  await api(`/api/learner-identities/${state.identityId}/preferences/${preferenceId}`, {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action}),
  });
  await refreshMemory();
}

async function actOnRetest(itemId, action) {
  if (action === "start") {
    const result = await api(`/api/learner-identities/${state.identityId}/retest-items/${itemId}/start`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({blueprint_id: state.blueprintId, profile: $("textProfile").value}),
    });
    state.sessionId = result.session_id;
    addMessage(result.turn);
    $("answerInput").disabled = false;
    $("sendAnswer").disabled = false;
    $("sessionState").textContent = "复测进行中";
    document.querySelector(".conversation").scrollIntoView({behavior: "smooth"});
    return;
  }
  await api(`/api/learner-identities/${state.identityId}/retest-items/${itemId}`, {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action, cooldown_days: 14}),
  });
  await refreshMemory();
}

async function waitForJob(jobId) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const job = await api(`/api/jobs/${jobId}`);
    setStatus("memoryStatus", `${job.message || job.status} · ${Math.round(job.progress * 100)}%`);
    if (job.status === "completed") return job;
    if (job.status === "failed") throw new Error(job.error || "后台任务失败");
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("后台任务等待超时");
}

$("preferenceKey").onchange = syncPreferenceValues;
syncPreferenceValues();

$("enableMemory").onclick = async () => {
  setStatus("memoryStatus", "正在创建并关联学习档案…");
  try { await enableMemory(); }
  catch (error) { setStatus("memoryStatus", error.message, "error"); }
};

$("importMemory").onclick = async () => {
  try {
    const imported = await api(`/api/learner-identities/${state.identityId}/memory/import`, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({dry_run: false}),
    });
    if (imported.imported > 0) {
      await api(`/api/learner-identities/${state.identityId}/memory/rebuild`, {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({algorithm_version: "evidence-half-life-v1"}),
      });
    }
    await refreshMemory();
    setStatus("memoryStatus", `已导入 ${imported.imported} 条新证据，跳过 ${imported.skipped} 条重复证据。`, "success");
  } catch (error) { setStatus("memoryStatus", error.message, "error"); }
};

$("refreshMemory").onclick = () => refreshMemory().catch((error) => setStatus("memoryStatus", error.message, "error"));

$("savePreference").onclick = async () => {
  try {
    await api(`/api/learner-identities/${state.identityId}/preferences`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({preference_key: $("preferenceKey").value, value: $("preferenceValue").value, source: "explicit"}),
    });
    await refreshMemory();
  } catch (error) { setStatus("memoryStatus", error.message, "error"); }
};

$("planRetest").onclick = async () => {
  try {
    await api(`/api/learner-identities/${state.identityId}/retest-plans`, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({horizon_days: 30, max_items: 8}),
    });
    await refreshMemory();
  } catch (error) { setStatus("memoryStatus", error.message, "error"); }
};

$("exportMemory").onclick = async () => {
  try {
    const queued = await api(`/api/learner-identities/${state.identityId}/memory/export`, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({include_source_quotes: false}),
    });
    const job = await waitForJob(queued.id);
    window.location.href = job.result.download_url;
  } catch (error) { setStatus("memoryStatus", error.message, "error"); }
};

$("deleteMemory").onclick = async () => {
  if (!window.confirm("确定删除全部长期认知状态、偏好和复测计划吗？原始项目与答辩记录不会删除。")) return;
  try {
    const queued = await api(`/api/learner-identities/${state.identityId}/memory`, {
      method: "DELETE", headers: {"Content-Type": "application/json"}, body: JSON.stringify({scope: "all_long_term_memory", confirmation: "delete"}),
    });
    await waitForJob(queued.job.id);
    await refreshMemory();
  } catch (error) { setStatus("memoryStatus", error.message, "error"); }
};

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

function latestVisualAnalyses(items) {
  const latest = new Map();
  for (const item of items) {
    if (!latest.has(item.evidence_asset_id)) latest.set(item.evidence_asset_id, item);
  }
  return [...latest.values()];
}

$("loadEvidence").onclick = loadEvidence;

$("analyzeVisual").onclick = async () => {
  if (!state.documentId) return;
  const profile = $("visualProfile").value || "mock:heuristic-v2";
  $("analyzeVisual").disabled = true;
  setStatus("evidenceStatus", "正在提交视觉证据分析任务…");
  try {
    const response = await api(`/api/documents/${state.documentId}/visual-analyses`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({profile, max_pages: 10, asynchronous: true}),
    });
    if (response.job) await pollJob(response.job.id);
    const history = await api(`/api/documents/${state.documentId}/visual-analyses`);
    const analyses = latestVisualAnalyses(history);
    const box = $("visualResults");
    box.classList.remove("hidden");
    box.innerHTML = `<strong>视觉审查结果</strong>${analyses.slice(0, 10).map((item) => `<div class="report-block">
      <h3>第 ${item.data.page_number || "?"} 页 · ${escapeHtml(item.data.visual_type || "page")}</h3>
      <p>${escapeHtml(item.data.summary || "")}</p>
      <ul>${list(item.data.potential_issues || [])}</ul>
      <ol>${(item.data.exam_questions || []).map((q) => `<li>${escapeHtml(q.question)}</li>`).join("")}</ol>
    </div>`).join("")}`;
    setStatus("evidenceStatus", `视觉分析完成：${analyses.length} 页（仅显示每页最新结果）。`, "success");
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

["templateSearch", "templateCategoryFilter", "templateRiskFilter", "templateLifecycleFilter"]
  .forEach((id) => {
    $(id).addEventListener(id === "templateSearch" ? "input" : "change", renderTemplateCatalog);
  });

$("refreshTemplates").onclick = () => loadTemplates();

$("sessionTemplateSelect").onchange = async () => {
  const versionId = $("sessionTemplateSelect").value;
  if (!versionId) {
    state.selectedTemplateVersionId = null;
    state.sessionTemplateSource = null;
    state.sessionTemplateLabel = "";
    setStatus("sessionTemplateHint", "使用兼容论文答辩模式；不会绑定显式模板。");
    syncBlueprintTemplateCompatibility();
    return;
  }
  try {
    const entry = state.publishedTemplates.find((item) => item.version_id === versionId);
    const version = await api(`/api/template-versions/${versionId}`);
    state.selectedTemplateVersionId = versionId;
    state.sessionTemplateSource = structuredClone(version.source);
    state.sessionTemplateLabel = localized(version.source.template?.title);
    $("questionStrategy").value = version.source.question_policy?.selection_strategy || "fixed";
    setStatus("sessionTemplateHint", `${state.sessionTemplateLabel} v${version.semantic_version} 将用于下一次蓝图和会话。`, "success");
    syncBlueprintTemplateCompatibility();
    if (entry) await selectTemplateIdentity(entry.id, versionId);
  } catch (error) {
    setStatus("sessionTemplateHint", error.message, "error");
  }
};

$("importTemplate").onclick = async () => {
  const file = $("templateImportFile").files[0];
  if (!file) return setStatus("templateImportStatus", "请选择 JSON 或 YAML 模板文件。", "error");
  const slug = $("templateImportSlug").value.trim();
  if (!slug) return setStatus("templateImportStatus", "请输入 local.* 形式的本地标识。", "error");
  try {
    setStatus("templateImportStatus", "正在进行安全解析和模板校验…");
    const documentText = await file.text();
    const result = await api("/api/templates/import", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        document: documentText,
        target_slug: slug,
        semantic_version: $("templateImportVersion").value.trim(),
      }),
    });
    await loadTemplates();
    await selectTemplateIdentity(result.template.id, result.version.id);
    setStatus("templateImportStatus", "模板已作为不受信任的本地草稿导入。", "success");
  } catch (error) {
    setStatus("templateImportStatus", error.message, "error");
  }
};

ensureVoiceProviderControl();
bootstrapWorkbenchIdentity().then((ready) => {
  if (!ready) return;
  loadEnvironment();
  loadTemplates();
});

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
  state.voiceInitialRequestAt = Date.now();
  if (state.voiceProvider === "openai") {
    sendRealtimeEvent({
      type: "conversation.item.create",
      item: {type: "message", role: "user", content: [{type: "input_text", text: "请开始本次答辩，用一句简短欢迎语后直接提出第一道问题。"}]},
    });
  }
  sendRealtimeEvent({type: "response.create", event_id: `event_start_${Date.now()}`});
  if (state.voiceProvider === "qwen") {
    clearTimeout(state.voiceInitialResponseTimer);
    state.voiceInitialResponseTimer = setTimeout(() => {
      if (!state.voiceInputReady) {
        setStatus("voiceStatus", "千问已连接，但首个问题响应超时。请结束语音后重试。", "error");
        setVoiceVisual("", "首个问题未能及时生成，请结束后重试。");
        persistVoiceEvent("error", null, "qwen_initial_response_timeout", null, {type: "client_timeout"});
      }
    }, 12000);
  }
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
    clearTimeout(state.voiceInitialResponseTimer);
    state.voiceInitialResponseTimer = null;
    setVoiceVisual("thinking", "正在生成回应…");
  } else if (type === "response.output_audio_transcript.delta" || type === "response.audio_transcript.delta") {
    setVoiceVisual("speaking", data.delta || "AI 正在说…");
    if (!state.voiceFirstResponseRecorded) {
      state.voiceFirstResponseRecorded = true;
      const latencyStart = state.voiceInitialRequestAt || state.voiceStartedAt;
      const latency = Math.max(0, Date.now() - latencyStart);
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
    const transcript = (data.transcript || "").trim();
    if (transcript) {
      addVoiceTranscript("user", transcript);
      persistVoiceEvent("transcript", "user", transcript, null, {type, item_id: data.item_id});
    }
  } else if (type === "conversation.item.input_audio_transcription.delta") {
    const preview = `${data.text || ""}${data.stash || ""}`;
    if (preview) setVoiceVisual("listening", preview);
  } else if (type === "response.done") {
    state.voiceInputReady = true;
    if (state.voiceStream) {
      state.voiceStream.getAudioTracks().forEach((track) => {
        track.enabled = !state.voiceMuted && !state.voicePtt;
      });
    }
    clearTimeout(state.voiceInitialResponseTimer);
    state.voiceInitialResponseTimer = null;
    setVoiceVisual("connected", "轮到您回答。直接说话即可。 ");
    const usage = data.response && data.response.usage ? data.response.usage : (data.usage || {});
    persistVoiceEvent("response_done", null, "", null, {type, usage});
  } else if (type === "error") {
    clearTimeout(state.voiceInitialResponseTimer);
    state.voiceInitialResponseTimer = null;
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
    if (!state.voiceInputReady || state.voiceMuted || !audioTrack || !audioTrack.enabled || socket.readyState !== WebSocket.OPEN) return;
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
      language: "zh-CN",
      voice: $("voiceSelect").value,
      vad_eagerness: $("vadSelect").value,
      learner_subject_key: `browser-${state.projectId}`,
      analysis_profile: $("textProfile").value || null,
      ...selectedTemplateRequest({includeVoice: true}),
      ...(!state.selectedTemplateVersionId ? {
        mode: "defense",
        question_limit: 6,
        max_followups: 2,
        question_strategy: $("questionStrategy").value,
      } : {}),
    }),
  });
  state.voiceSessionId = voiceSession.id;
  state.learnerSubjectId = voiceSession.learner_subject_id;
  $("enableMemory").disabled = false;
  state.voiceStartedAt = Date.now();
  state.voiceInitialRequestAt = 0;
  state.voiceFirstResponseRecorded = false;
  state.voiceInitialResponseSent = false;
  state.voiceInputReady = false;
  clearTimeout(state.voiceInitialResponseTimer);
  state.voiceInitialResponseTimer = null;
  state.voiceProvider = provider.id;
  state.voiceClientConfig = voiceSession.client_config || null;

  const stream = await getUserMediaWithTimeout({
    audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1},
  });
  stream.getAudioTracks().forEach((track) => { track.enabled = false; });
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
  const sdpController = new AbortController();
  const sdpTimeout = setTimeout(() => sdpController.abort(), 20000);
  let response;
  try {
    response = await fetch(`/api/voice/sessions/${voiceSession.id}/sdp`, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/sdp",
        ...(state.organizationId ? {"X-AI-Examiner-Organization": state.organizationId} : {}),
      },
      body: pc.localDescription.sdp,
      signal: sdpController.signal,
    });
  } catch (error) {
    if (error.name === "AbortError") throw new Error("实时语音协商超时，请检查模型服务和服务器网络后重试。");
    throw error;
  } finally {
    clearTimeout(sdpTimeout);
  }
  const raw = await response.text();
  if (!response.ok) {
    let body = raw;
    try { body = JSON.parse(raw); } catch {}
    throw new Error(responseErrorMessage(body, response.status));
  }
  await pc.setRemoteDescription({type: "answer", sdp: raw});
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
  $("endVoice").disabled = true;
  setStatus("voiceStatus", "正在结束语音并整理转录记录…");
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
  state.voiceInitialRequestAt = 0;
  state.voiceInputReady = false;
  clearTimeout(state.voiceInitialResponseTimer);
  state.voiceInitialResponseTimer = null;
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
  if (state.voiceSessionId) {
    fetch(`/api/voice/sessions/${state.voiceSessionId}/complete`, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        ...(state.organizationId ? {"X-AI-Examiner-Organization": state.organizationId} : {}),
      },
      body: JSON.stringify({reason: "page_unload"}),
      keepalive: true,
    }).catch(() => {});
  }
});

if (state.identityId) {
  ["importMemory", "refreshMemory", "exportMemory", "deleteMemory", "savePreference", "planRetest"]
    .forEach((id) => { $(id).disabled = false; });
  refreshMemory().catch(() => {
    state.identityId = null;
    localStorage.removeItem("ai-examiner-identity-id");
    $("memoryState").textContent = "尚未启用";
  });
}
