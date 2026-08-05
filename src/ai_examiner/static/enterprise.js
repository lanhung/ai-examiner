const state = {
  authMethod: "unknown",
  principal: null,
  organizations: [],
  organizationId: null,
  context: null,
  capabilities: new Set(),
  epoch: 0,
  controllers: new Set(),
  view: "overview",
  auditCursor: null,
  selectedReviewId: null,
};

const roles = [
  "owner", "admin", "examiner", "template_author", "reviewer", "learner", "auditor",
];
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}
class StaleOrganizationError extends Error {}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? String(value)
    : new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "short",
        timeStyle: "medium",
      }).format(date);
}

function formatMoney(value) {
  if (value === null || value === undefined) return "不限";
  return `$${Number(value).toFixed(4)}`;
}

function setRequestState(text) {
  $("#requestState").textContent = text;
}

function toast(message, type = "") {
  const item = document.createElement("div");
  item.className = `toast ${type}`.trim();
  item.textContent = message;
  $("#toastRegion").append(item);
  window.setTimeout(() => item.remove(), 5000);
}

function errorMessage(error) {
  if (error instanceof StaleOrganizationError) return "";
  const detail = error?.payload?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  if (Array.isArray(detail)) return detail.map((item) => item.msg).join("; ");
  return error?.message || "请求失败";
}

function showLoginRequired() {
  state.authMethod = "oidc";
  state.principal = null;
  state.organizations = [];
  state.organizationId = null;
  $("#authBadge").textContent = "未登录";
  $("#authBadge").className = "status-badge warning";
  $("#loginRequired").classList.remove("hidden");
  $("#workspace").classList.add("hidden");
  $("#organizationSelect").disabled = true;
  $("#logoutButton").classList.add("hidden");
}

function isOidcAuthMethod(method) {
  return method === "oidc" || String(method || "").startsWith("oidc_");
}

function developerHeaders() {
  if (state.authMethod !== "disabled") return {};
  const principalId = localStorage.getItem("ai-examiner.dev-principal");
  return principalId ? {"X-AI-Examiner-Principal": principalId} : {};
}

function organizationResponseId(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  return payload.organization_id
    || payload.organization?.id
    || payload.authorization?.organization_id
    || null;
}

async function api(path, options = {}) {
  const organizationScoped = options.organizationScoped !== false;
  const capturedOrganization = state.organizationId;
  const capturedEpoch = state.epoch;
  const controller = new AbortController();
  state.controllers.add(controller);
  const headers = {
    Accept: "application/json",
    ...developerHeaders(),
    ...(options.headers || {}),
  };
  if (organizationScoped && capturedOrganization) {
    headers["X-AI-Examiner-Organization"] = capturedOrganization;
  }
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  setRequestState("正在读取");
  try {
    const response = await fetch(path, {
      method: options.method || "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers,
      body: options.body === undefined
        ? undefined
        : options.body instanceof FormData
          ? options.body
          : JSON.stringify(options.body),
      signal: controller.signal,
    });
    const raw = await response.text();
    let payload = null;
    if (raw) {
      try { payload = JSON.parse(raw); } catch { payload = raw; }
    }
    if (!response.ok) {
      const error = new ApiError(
        typeof payload === "string" ? payload : `请求失败 (${response.status})`,
        response.status,
        payload,
      );
      if (response.status === 401) showLoginRequired();
      throw error;
    }
    if (organizationScoped) {
      if (
        capturedEpoch !== state.epoch
        || capturedOrganization !== state.organizationId
      ) {
        throw new StaleOrganizationError();
      }
      const responseOrganization = organizationResponseId(payload);
      if (responseOrganization && responseOrganization !== capturedOrganization) {
        throw new StaleOrganizationError();
      }
    }
    return payload;
  } catch (error) {
    if (error.name === "AbortError") throw new StaleOrganizationError();
    throw error;
  } finally {
    state.controllers.delete(controller);
    if (capturedEpoch === state.epoch) setRequestState("就绪");
  }
}

async function download(path, filename) {
  const capturedOrganization = state.organizationId;
  const capturedEpoch = state.epoch;
  const controller = new AbortController();
  state.controllers.add(controller);
  try {
    const response = await fetch(path, {
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        ...developerHeaders(),
        "X-AI-Examiner-Organization": capturedOrganization,
      },
      signal: controller.signal,
    });
    if (!response.ok) {
      const raw = await response.text();
      throw new ApiError(raw || "导出失败", response.status, null);
    }
    const blob = await response.blob();
    if (
      capturedEpoch !== state.epoch
      || capturedOrganization !== state.organizationId
    ) throw new StaleOrganizationError();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  } finally {
    state.controllers.delete(controller);
  }
}

function abortOrganizationRequests() {
  state.controllers.forEach((controller) => controller.abort());
  state.controllers.clear();
}

function can(capability) {
  return state.capabilities.has(capability);
}

function statusBadge(status) {
  const danger = ["failed", "denied", "revoked", "cancelled"];
  const warning = ["requested", "blocked", "suspended", "invited", "appealed"];
  const success = ["active", "completed", "succeeded", "decided", "released"];
  const tone = danger.includes(status)
    ? "danger"
    : warning.includes(status)
      ? "warning"
      : success.includes(status)
        ? "success"
        : "neutral";
  return `<span class="status-badge ${tone}">${escapeHtml(status || "unknown")}</span>`;
}

function emptyRow(message, columns) {
  return `<tr><td colspan="${columns}"><div class="empty-state compact"><p>${escapeHtml(message)}</p></div></td></tr>`;
}

function clearOrganizationData() {
  $("#overviewMetrics").innerHTML = "";
  $("#authorizationSummary").innerHTML = "";
  $("#capabilityList").innerHTML = "";
  $("#memberRows").innerHTML = emptyRow("正在读取成员", 6);
  $("#usageMetrics").innerHTML = "";
  $("#auditRows").innerHTML = emptyRow("正在读取审计事件", 6);
  $("#legalHoldList").innerHTML = "";
  $("#dataRequestList").innerHTML = "";
  $("#reviewCaseList").innerHTML = "";
  $("#reviewDetail").innerHTML = '<div class="empty-state compact"><p>选择一个复核案例查看详情。</p></div>';
  state.auditCursor = null;
  state.selectedReviewId = null;
}

function applyCapabilities() {
  $$("[data-capability]").forEach((element) => {
    element.classList.toggle(
      "hidden-by-capability",
      !can(element.dataset.capability),
    );
  });
  $$("[data-requires]").forEach((element) => {
    const allowed = can(element.dataset.requires);
    element.disabled = !allowed;
    element.title = allowed ? "" : `缺少权限：${element.dataset.requires}`;
  });
  const activeNav = $(`#navigation button[data-view="${state.view}"]`);
  if (!activeNav || activeNav.classList.contains("hidden-by-capability")) {
    switchView("overview");
  }
}

function populateOrganizationSelect() {
  const select = $("#organizationSelect");
  select.innerHTML = "";
  if (state.organizations.length) {
    state.organizations.forEach((organization) => {
      const option = document.createElement("option");
      option.value = organization.id;
      option.textContent = organization.display_name || organization.slug || organization.id;
      select.append(option);
    });
  } else if (state.organizationId) {
    const option = document.createElement("option");
    option.value = state.organizationId;
    option.textContent = state.context?.organization?.display_name || state.organizationId;
    select.append(option);
  } else {
    select.append(new Option("未选择", ""));
  }
  select.value = state.organizationId || "";
  select.disabled = state.organizations.length < 2;
}

async function activateOrganization(organizationId) {
  if (!organizationId) return;
  abortOrganizationRequests();
  state.epoch += 1;
  state.organizationId = organizationId;
  state.context = null;
  state.capabilities = new Set();
  localStorage.setItem("ai-examiner.organization", organizationId);
  clearOrganizationData();
  $("#workspace").classList.add("hidden");
  $("#organizationName").textContent = "正在读取组织";
  $("#organizationMeta").textContent = organizationId;
  populateOrganizationSelect();
  try {
    const context = await api("/api/v1/context");
    if (context.organization?.id !== organizationId) {
      throw new StaleOrganizationError();
    }
    state.context = context;
    state.capabilities = new Set(context.capabilities || []);
    const organization = state.organizations.find((item) => item.id === organizationId);
    if (organization) Object.assign(organization, context.organization);
    else state.organizations.push(context.organization);
    populateOrganizationSelect();
    $("#organizationSelect").title =
      `${context.organization.display_name} · ${context.organization.id}`;
    $("#organizationName").textContent = context.organization.display_name;
    $("#organizationMeta").textContent = `${context.organization.slug} · ${context.role || "context"}`;
    $("#workspace").classList.remove("hidden");
    applyCapabilities();
    await loadView(state.view);
  } catch (error) {
    const message = errorMessage(error);
    if (message) {
      toast(message, "error");
      $("#organizationName").textContent = "无法访问组织";
      $("#organizationMeta").textContent = message;
    }
  }
}

function switchView(view) {
  state.view = view;
  $$(".view").forEach((element) => element.classList.remove("active"));
  $$("#navigation button").forEach((element) => element.classList.remove("active"));
  $(`#view-${view}`)?.classList.add("active");
  $(`#navigation button[data-view="${view}"]`)?.classList.add("active");
}

async function loadView(view) {
  const loaders = {
    overview: loadOverview,
    members: loadMembers,
    governance: loadGovernance,
    audit: () => loadAudit(false),
    lifecycle: loadLifecycle,
    reviews: loadReviews,
  };
  try {
    await loaders[view]?.();
  } catch (error) {
    const message = errorMessage(error);
    if (message) toast(message, "error");
  }
}

function renderMetrics(target, metrics) {
  $(target).innerHTML = metrics.map((metric) => `
    <div class="metric">
      <span>${escapeHtml(metric.label)}</span>
      <strong>${escapeHtml(metric.value)}</strong>
      ${metric.note ? `<small>${escapeHtml(metric.note)}</small>` : ""}
    </div>
  `).join("");
}

async function loadOverview() {
  const captured = state.epoch;
  const organization = await api(`/api/v1/organizations/${state.organizationId}`);
  const optional = await Promise.allSettled([
    can("member.read")
      ? api(`/api/v1/organizations/${state.organizationId}/memberships`)
      : Promise.resolve(null),
    can("usage.read")
      ? api(`/api/v1/organizations/${state.organizationId}/usage`)
      : Promise.resolve(null),
    can("review_case.review")
      ? api(`/api/v1/organizations/${state.organizationId}/review-cases`)
      : Promise.resolve(null),
    can("retention.read")
      ? api(`/api/v1/organizations/${state.organizationId}/data-subject-requests?limit=200`)
      : Promise.resolve(null),
  ]);
  if (captured !== state.epoch) return;
  const value = (index) => optional[index].status === "fulfilled" ? optional[index].value : null;
  const memberships = value(0);
  const usage = value(1);
  const reviews = value(2);
  const requests = value(3);
  renderMetrics("#overviewMetrics", [
    {label: "活跃成员", value: memberships?.items?.filter((item) => item.status === "active").length ?? "—", note: memberships ? `共 ${memberships.count} 个成员记录` : "无查看权限"},
    {label: "本月模型费用", value: usage ? formatMoney(usage.committed_cost_usd) : "—", note: usage ? `${usage.completed_calls} 次完成调用` : "无查看权限"},
    {label: "待处理复核", value: reviews?.items?.filter((item) => ["open", "assigned", "appealed"].includes(item.status)).length ?? "—", note: reviews ? `共 ${reviews.items.length} 个案例` : "无查看权限"},
    {label: "数据请求", value: requests?.count ?? "—", note: requests ? `${requests.items.filter((item) => ["requested", "blocked", "failed"].includes(item.status)).length} 项需关注` : "无查看权限"},
  ]);
  const auth = organization.authorization;
  $("#authorizationSummary").innerHTML = [
    ["组织", organization.organization.display_name],
    ["组织标识", organization.organization.slug],
    ["主体", state.principal?.display_name || auth.principal_id],
    ["角色", auth.role],
    ["认证方式", auth.authentication_method],
    ["授权模式", auth.authorization_enforced ? "强制执行" : "兼容模式"],
  ].map(([term, description]) => `<dt>${escapeHtml(term)}</dt><dd>${escapeHtml(description)}</dd>`).join("");
  $("#capabilityList").innerHTML = [...state.capabilities]
    .sort()
    .map((item) => `<span class="tag">${escapeHtml(item)}</span>`)
    .join("");
  $("#overviewUpdated").textContent = `更新于 ${formatDate(new Date().toISOString())}`;
}

function principalLabel(item) {
  return item.principal?.display_name
    || item.principal?.email
    || item.principal_id;
}

async function loadMembers() {
  const payload = await api(`/api/v1/organizations/${state.organizationId}/memberships`);
  $("#memberRows").innerHTML = payload.items.length
    ? payload.items.map((item) => {
        const controls = can("member.manage") && item.status !== "revoked" ? `
          <div class="row-actions" data-membership="${escapeHtml(item.id)}" data-version="${item.version}">
            <select class="member-role" aria-label="角色">${roles.map((role) => `<option ${role === item.role ? "selected" : ""}>${role}</option>`).join("")}</select>
            <select class="member-status" aria-label="状态">${["active", "suspended"].map((status) => `<option ${status === item.status ? "selected" : ""}>${status}</option>`).join("")}</select>
            <button class="button secondary compact member-save">保存</button>
            <button class="button secondary compact member-revoke">撤销</button>
          </div>` : "—";
        return `<tr>
          <td><strong>${escapeHtml(principalLabel(item))}</strong><br><span class="mono muted">${escapeHtml(item.principal_id)}</span></td>
          <td>${escapeHtml(item.role)}</td>
          <td>${statusBadge(item.status)}</td>
          <td>${item.version}</td>
          <td>${formatDate(item.updated_at)}</td>
          <td class="actions">${controls}</td>
        </tr>`;
      }).join("")
    : emptyRow("当前组织还没有成员", 6);
}

async function saveMember(container) {
  const id = container.dataset.membership;
  const version = container.dataset.version;
  await api(`/api/v1/organizations/${state.organizationId}/memberships/${id}`, {
    method: "PATCH",
    headers: {"If-Match": `"${version}"`},
    body: {
      role: $(".member-role", container).value,
      status: $(".member-status", container).value,
    },
  });
  toast("成员权限已更新");
  await loadMembers();
}

async function revokeMember(container) {
  const confirmed = await confirmAction({
    title: "撤销成员资格",
    message: "该成员将立即失去组织访问权限。此操作需要明确确认。",
    phrase: "REVOKE",
  });
  if (!confirmed) return;
  await api(
    `/api/v1/organizations/${state.organizationId}/memberships/${container.dataset.membership}`,
    {method: "DELETE", headers: {"If-Match": `"${container.dataset.version}"`}},
  );
  toast("成员资格已撤销");
  await loadMembers();
}

function profilesToText(profiles) {
  return (profiles || []).map((item) =>
    `${item.provider}:${item.model_pattern} | ${(item.tasks || ["*"]).join(",")}`
  ).join("\n");
}

function parseProfiles(text) {
  return text.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
    const [profile, taskText = "*"] = line.split("|").map((part) => part.trim());
    const separator = profile.indexOf(":");
    if (separator < 1) throw new Error(`无效模型配置：${line}`);
    return {
      provider: profile.slice(0, separator),
      model_pattern: profile.slice(separator + 1),
      tasks: taskText.split(",").map((item) => item.trim()).filter(Boolean),
    };
  });
}

function setFormValues(form, payload, fields) {
  fields.forEach((field) => {
    const input = form.elements[field];
    if (!input) return;
    if (input.type === "checkbox") input.checked = Boolean(payload[field]);
    else input.value = payload[field] ?? "";
  });
}

async function loadGovernance() {
  const [policy, quota, usage] = await Promise.all([
    api(`/api/v1/organizations/${state.organizationId}/model-policy`),
    api(`/api/v1/organizations/${state.organizationId}/quota`),
    can("usage.read")
      ? api(`/api/v1/organizations/${state.organizationId}/usage`)
      : Promise.resolve(null),
  ]);
  const policyForm = $("#modelPolicyForm");
  policyForm.elements.allowed_profiles.value = profilesToText(policy.allowed_profiles);
  policyForm.elements.fallback_profiles.value = (policy.fallback_profiles || []).join("\n");
  setFormValues(policyForm, policy, [
    "external_provider_max_classification", "fallback_mode", "provider_retention_allowed",
  ]);
  $("#modelPolicyVersion").textContent = `v${policy.version}`;
  setFormValues($("#quotaForm"), quota, [
    "quota_mode", "monthly_budget_usd", "per_session_budget_usd",
    "per_request_budget_usd", "soft_limit_ratio",
    "organization_requests_per_minute", "principal_requests_per_minute",
    "organization_tokens_per_minute", "max_concurrent_calls",
  ]);
  $("#quotaVersion").textContent = `v${quota.version}`;
  renderMetrics("#usageMetrics", [
    {label: "本月已提交费用", value: usage ? formatMoney(usage.committed_cost_usd) : "—", note: usage ? `预算 ${formatMoney(usage.monthly_budget_usd)}` : "无使用量查看权限"},
    {label: "剩余预算", value: usage ? formatMoney(usage.remaining_budget_usd) : "—", note: usage?.quota_mode || ""},
    {label: "完成调用", value: usage?.completed_calls ?? "—", note: usage ? `${usage.failed_calls} 次失败，${usage.denied_calls} 次拒绝` : ""},
    {label: "Token", value: usage ? (usage.input_tokens + usage.output_tokens).toLocaleString() : "—", note: usage ? `输入 ${usage.input_tokens.toLocaleString()} / 输出 ${usage.output_tokens.toLocaleString()}` : ""},
  ]);
}

function auditQuery(includeCursor = false) {
  const params = new URLSearchParams();
  const data = new FormData($("#auditFilters"));
  for (const [key, value] of data.entries()) {
    if (String(value).trim()) params.set(key, String(value).trim());
  }
  params.set("limit", "50");
  if (includeCursor && state.auditCursor) params.set("cursor", state.auditCursor);
  return params;
}

async function loadAudit(append) {
  if (!append) state.auditCursor = null;
  const payload = await api(
    `/api/v1/organizations/${state.organizationId}/audit-events?${auditQuery(append)}`,
  );
  const rows = payload.items.map((item) => `<tr>
    <td>${formatDate(item.occurred_at || item.created_at)}</td>
    <td><strong>${escapeHtml(item.action)}</strong></td>
    <td class="mono">${escapeHtml(item.actor_principal_id || item.actor_id || "system")}</td>
    <td>${escapeHtml(item.resource_type)}<br><span class="mono muted">${escapeHtml(item.resource_id || "—")}</span></td>
    <td>${statusBadge(item.outcome)}</td>
    <td class="mono">${escapeHtml(item.request_id || "—")}</td>
  </tr>`).join("");
  if (append) $("#auditRows").insertAdjacentHTML("beforeend", rows);
  else $("#auditRows").innerHTML = rows || emptyRow("没有符合筛选条件的审计事件", 6);
  state.auditCursor = payload.next_cursor;
  $("#auditNext").classList.toggle("hidden", !state.auditCursor);
  $("#auditRetention").textContent = `审计保留 ${payload.retention.configured_days} 天 · 运行时删除已禁用`;
}

async function loadLifecycle() {
  const [policy, holds, requests] = await Promise.all([
    api(`/api/v1/organizations/${state.organizationId}/retention-policy`),
    api(`/api/v1/organizations/${state.organizationId}/legal-holds`),
    api(`/api/v1/organizations/${state.organizationId}/data-subject-requests?${dataRequestQuery()}`),
  ]);
  setFormValues($("#retentionForm"), policy, [
    "policy_mode", "project_days", "session_days", "document_days",
    "learner_memory_days", "export_ttl_hours", "deletion_grace_days",
  ]);
  $("#retentionVersion").textContent = `v${policy.version}`;
  renderLegalHolds(holds.items);
  renderDataRequests(requests.items);
}

function renderLegalHolds(items) {
  $("#legalHoldList").innerHTML = items.length ? items.map((item) => `
    <article class="record">
      <div class="record-head"><strong>${escapeHtml(item.scope_type)}${item.scope_id ? ` · ${escapeHtml(item.scope_id)}` : ""}</strong>${statusBadge(item.status)}</div>
      <p>${escapeHtml(item.reason)}</p>
      <div class="record-meta"><span>${formatDate(item.created_at)}</span><span class="mono">${escapeHtml(item.id)}</span></div>
      ${item.status === "active" && can("retention.manage") ? `<div class="record-actions"><button class="button secondary compact release-hold" data-id="${escapeHtml(item.id)}">释放保全</button></div>` : ""}
    </article>
  `).join("") : '<div class="empty-state compact"><p>没有法务保全记录。</p></div>';
}

function dataRequestQuery() {
  const params = new URLSearchParams({limit: "100"});
  if ($("#dataRequestStatus").value) params.set("status", $("#dataRequestStatus").value);
  if ($("#dataRequestType").value) params.set("request_type", $("#dataRequestType").value);
  return params;
}

function renderDataRequests(items) {
  $("#dataRequestList").innerHTML = items.length ? items.map((item) => {
    const canManage = can("retention.manage");
    const actions = [];
    if (canManage && item.status === "requested") {
      actions.push(`<button class="button compact data-approve" data-id="${item.id}" data-type="${item.request_type}">批准</button>`);
      actions.push(`<button class="button secondary compact data-cancel" data-id="${item.id}">取消</button>`);
    }
    if (canManage && ["blocked", "failed"].includes(item.status) && item.final_decision === "approved") {
      actions.push(`<button class="button secondary compact data-retry" data-id="${item.id}">重试</button>`);
    }
    return `<article class="record">
      <div class="record-head"><strong>${escapeHtml(item.request_type)} · ${escapeHtml(item.target_type)}</strong>${statusBadge(item.status)}</div>
      <p class="mono">${escapeHtml(item.target_id)}</p>
      <div class="record-meta"><span>${formatDate(item.requested_at)}</span><span>决定：${escapeHtml(item.final_decision || "待定")}</span></div>
      ${actions.length ? `<div class="record-actions">${actions.join("")}</div>` : ""}
    </article>`;
  }).join("") : '<div class="empty-state compact"><p>没有数据主体请求。</p></div>';
}

async function refreshDataRequests() {
  const payload = await api(`/api/v1/organizations/${state.organizationId}/data-subject-requests?${dataRequestQuery()}`);
  renderDataRequests(payload.items);
}

async function loadReviews() {
  const query = $("#reviewStatus").value
    ? `?status=${encodeURIComponent($("#reviewStatus").value)}`
    : "";
  const payload = await api(`/api/v1/organizations/${state.organizationId}/review-cases${query}`);
  $("#reviewCaseList").innerHTML = payload.items.length ? payload.items.map((item) => `
    <article class="record review-case ${item.id === state.selectedReviewId ? "selected" : ""}" data-id="${escapeHtml(item.id)}">
      <div class="record-head"><strong>${escapeHtml(item.title)}</strong>${statusBadge(item.status)}</div>
      <p>${escapeHtml(item.summary || "无摘要")}</p>
      <div class="record-meta"><span>${escapeHtml(item.case_type)}</span><span>${formatDate(item.created_at)}</span></div>
    </article>
  `).join("") : '<div class="empty-state compact"><p>当前筛选下没有复核案例。</p></div>';
  if (state.selectedReviewId && payload.items.some((item) => item.id === state.selectedReviewId)) {
    await loadReviewDetail(state.selectedReviewId);
  }
}

async function loadReviewDetail(caseId) {
  state.selectedReviewId = caseId;
  $$(".review-case").forEach((element) => element.classList.toggle("selected", element.dataset.id === caseId));
  const item = await api(`/api/v1/review-cases/${caseId}`);
  const actions = can("review_case.review") ? `
    <div class="two-column">
      <form id="assignReviewForm" class="subform">
        <label>分配给主体 ID<input name="principal_id" required maxlength="36" value="${escapeHtml(item.assigned_principal_id || "")}" /></label>
        <button class="button secondary" type="submit">更新分配</button>
      </form>
      <form id="decisionReviewForm" class="subform">
        <label>决定<input name="decision" required placeholder="upheld / partially_upheld" /></label>
        <label>理由<textarea name="reason" required minlength="5"></textarea></label>
        <button class="button" type="submit">提交人工决定</button>
      </form>
    </div>` : "";
  $("#reviewDetail").innerHTML = `
    <div class="surface-heading"><div><h2>${escapeHtml(item.title)}</h2><span class="muted">${escapeHtml(item.case_type)} · ${escapeHtml(item.resource_type)}</span></div>${statusBadge(item.status)}</div>
    <p>${escapeHtml(item.summary || "无摘要")}</p>
    <dl class="definition-list">
      <dt>资源 ID</dt><dd class="mono">${escapeHtml(item.resource_id)}</dd>
      <dt>分配成员</dt><dd>${escapeHtml(item.assigned_principal_id || "未分配")}</dd>
      <dt>最终决定</dt><dd>${escapeHtml(item.final_decision || "待定")}</dd>
      <dt>创建时间</dt><dd>${formatDate(item.created_at)}</dd>
    </dl>
    ${actions}
    <div class="surface-heading" style="margin-top:20px"><h2>事件时间线</h2><span class="muted">${item.events?.length || 0} 条</span></div>
    <div class="event-timeline">${(item.events || []).map((event) => `
      <div class="event"><strong>${escapeHtml(event.event_type)}</strong><span class="muted"> · ${formatDate(event.created_at)}</span><p>${escapeHtml(JSON.stringify(event.payload || {}))}</p></div>
    `).join("") || '<p class="muted">暂无事件。</p>'}</div>
  `;
}

function confirmAction({title, message, phrase = ""}) {
  const dialog = $("#confirmDialog");
  $("#confirmTitle").textContent = title;
  $("#confirmMessage").textContent = message;
  $("#confirmPhraseWrap").classList.toggle("hidden", !phrase);
  $("#confirmPhrase").textContent = phrase;
  $("#confirmInput").value = "";
  $("#confirmAction").disabled = Boolean(phrase);
  const listener = () => {
    $("#confirmAction").disabled = phrase && $("#confirmInput").value !== phrase;
  };
  $("#confirmInput").addEventListener("input", listener);
  dialog.showModal();
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => {
      $("#confirmInput").removeEventListener("input", listener);
      resolve(dialog.returnValue === "confirm" && (!phrase || $("#confirmInput").value === phrase));
    }, {once: true});
  });
}

async function submitJsonForm(form, fields) {
  const result = {};
  fields.forEach((field) => {
    const input = form.elements[field];
    if (input.type === "checkbox") result[field] = input.checked;
    else if (input.type === "number") result[field] = Number(input.value);
    else result[field] = input.value;
  });
  return result;
}

function bindEvents() {
  $("#navigation").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-view]");
    if (!button || button.classList.contains("hidden-by-capability")) return;
    switchView(button.dataset.view);
    await loadView(button.dataset.view);
  });
  $("#organizationSelect").addEventListener("change", (event) => activateOrganization(event.target.value));
  $("#refreshCurrent").addEventListener("click", () => loadView(state.view));
  $("#logoutButton").addEventListener("click", async () => {
    await api("/api/v1/auth/logout", {method: "POST", organizationScoped: false});
    window.location.reload();
  });
  $("#developerContextForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const organizationId = $("#developerOrganizationId").value.trim();
    const principalId = $("#developerPrincipalId").value.trim();
    localStorage.setItem("ai-examiner.dev-principal", principalId);
    state.organizations = [{id: organizationId, display_name: organizationId}];
    await activateOrganization(organizationId);
  });
  $$("[data-close-form]").forEach((button) => button.addEventListener("click", () => $(`#${button.dataset.closeForm}`).classList.add("hidden")));

  $("#openAddMember").addEventListener("click", () => $("#memberForm").classList.remove("hidden"));
  $("#memberForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = await submitJsonForm(event.currentTarget, ["principal_id", "role", "status"]);
    try {
      await api(`/api/v1/organizations/${state.organizationId}/memberships`, {method: "POST", body});
      event.currentTarget.reset();
      event.currentTarget.classList.add("hidden");
      toast("成员已添加");
      await loadMembers();
    } catch (error) { toast(errorMessage(error), "error"); }
  });
  $("#memberRows").addEventListener("click", async (event) => {
    const container = event.target.closest("[data-membership]");
    if (!container) return;
    try {
      if (event.target.closest(".member-save")) await saveMember(container);
      if (event.target.closest(".member-revoke")) await revokeMember(container);
    } catch (error) { toast(errorMessage(error), "error"); }
  });

  $("#modelPolicyForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const form = event.currentTarget;
      await api(`/api/v1/organizations/${state.organizationId}/model-policy`, {
        method: "PUT",
        body: {
          allowed_profiles: parseProfiles(form.elements.allowed_profiles.value),
          fallback_profiles: form.elements.fallback_profiles.value.split("\n").map((item) => item.trim()).filter(Boolean),
          external_provider_max_classification: form.elements.external_provider_max_classification.value,
          fallback_mode: form.elements.fallback_mode.value,
          provider_retention_allowed: form.elements.provider_retention_allowed.checked,
        },
      });
      toast("模型策略已保存");
      await loadGovernance();
    } catch (error) { toast(errorMessage(error), "error"); }
  });
  $("#quotaForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const body = await submitJsonForm(event.currentTarget, [
        "quota_mode", "monthly_budget_usd", "per_session_budget_usd",
        "per_request_budget_usd", "soft_limit_ratio",
        "organization_requests_per_minute", "principal_requests_per_minute",
        "organization_tokens_per_minute", "max_concurrent_calls",
      ]);
      await api(`/api/v1/organizations/${state.organizationId}/quota`, {method: "PUT", body});
      toast("配额与限流已保存");
      await loadGovernance();
    } catch (error) { toast(errorMessage(error), "error"); }
  });
  $("#downloadUsage").addEventListener("click", async () => {
    try { await download(`/api/v1/organizations/${state.organizationId}/usage/export`, `model-usage-${state.organizationId}.jsonl`); }
    catch (error) { toast(errorMessage(error), "error"); }
  });

  $("#auditFilters").addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await loadAudit(false); } catch (error) { toast(errorMessage(error), "error"); }
  });
  $("#auditNext").addEventListener("click", async () => {
    try { await loadAudit(true); } catch (error) { toast(errorMessage(error), "error"); }
  });
  $("#downloadAudit").addEventListener("click", async () => {
    try { await download(`/api/v1/organizations/${state.organizationId}/audit-events/export?${auditQuery(false)}`, `audit-${state.organizationId}.jsonl`); }
    catch (error) { toast(errorMessage(error), "error"); }
  });

  $("#retentionForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const body = await submitJsonForm(event.currentTarget, [
        "policy_mode", "project_days", "session_days", "document_days",
        "learner_memory_days", "export_ttl_hours", "deletion_grace_days",
      ]);
      await api(`/api/v1/organizations/${state.organizationId}/retention-policy`, {method: "PUT", body});
      toast("保留策略已保存");
      await loadLifecycle();
    } catch (error) { toast(errorMessage(error), "error"); }
  });
  $("#openLegalHold").addEventListener("click", () => $("#legalHoldForm").classList.remove("hidden"));
  $("#legalHoldForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    try {
      await api(`/api/v1/organizations/${state.organizationId}/legal-holds`, {
        method: "POST",
        body: {
          scope_type: form.elements.scope_type.value,
          scope_id: form.elements.scope_type.value === "organization" ? null : form.elements.scope_id.value.trim(),
          reason: form.elements.reason.value,
        },
      });
      form.reset();
      form.classList.add("hidden");
      toast("法务保全已创建");
      await loadLifecycle();
    } catch (error) { toast(errorMessage(error), "error"); }
  });
  $("#legalHoldList").addEventListener("click", async (event) => {
    const button = event.target.closest(".release-hold");
    if (!button) return;
    const confirmed = await confirmAction({
      title: "释放法务保全",
      message: "释放后，相关数据可能进入保留策略的删除流程。",
      phrase: "RELEASE",
    });
    if (!confirmed) return;
    try {
      await api(`/api/v1/legal-holds/${button.dataset.id}/release`, {
        method: "POST",
        body: {reason: "Released through enterprise console after explicit confirmation"},
      });
      toast("法务保全已释放");
      await loadLifecycle();
    } catch (error) { toast(errorMessage(error), "error"); }
  });
  $("#openDataRequest").addEventListener("click", () => $("#dataRequestForm").classList.remove("hidden"));
  $("#dataRequestStatus").addEventListener("change", refreshDataRequests);
  $("#dataRequestType").addEventListener("change", refreshDataRequests);
  $("#dataRequestForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    try {
      await api(`/api/v1/organizations/${state.organizationId}/data-subject-requests`, {
        method: "POST",
        headers: {"Idempotency-Key": crypto.randomUUID()},
        body: {
          request_type: form.elements.request_type.value,
          target_type: form.elements.target_type.value,
          target_id: form.elements.target_id.value.trim(),
          reason: form.elements.reason.value,
          include_objects: form.elements.include_objects.checked,
        },
      });
      form.reset();
      form.classList.add("hidden");
      toast("数据主体请求已创建");
      await refreshDataRequests();
    } catch (error) { toast(errorMessage(error), "error"); }
  });
  $("#dataRequestList").addEventListener("click", async (event) => {
    const approve = event.target.closest(".data-approve");
    const cancel = event.target.closest(".data-cancel");
    const retry = event.target.closest(".data-retry");
    const button = approve || cancel || retry;
    if (!button) return;
    try {
      if (approve) {
        const isDelete = approve.dataset.type === "delete";
        const confirmed = await confirmAction({
          title: isDelete ? "批准不可逆删除" : "批准数据导出",
          message: isDelete
            ? "批准后将执行双人控制的数据删除并验证对象存储。"
            : "批准后将创建包含受控数据的导出工件。",
          phrase: isDelete ? "DELETE" : "APPROVE",
        });
        if (!confirmed) return;
        await api(`/api/v1/data-subject-requests/${approve.dataset.id}/approve`, {
          method: "POST",
          headers: {"Idempotency-Key": crypto.randomUUID()},
          body: {decision: "approved", reason: "Approved through enterprise console after explicit confirmation"},
        });
      } else if (cancel) {
        const confirmed = await confirmAction({title: "取消数据请求", message: "该请求将不再进入执行流程。"});
        if (!confirmed) return;
        await api(`/api/v1/data-subject-requests/${cancel.dataset.id}/cancel`, {
          method: "POST",
          body: {reason: "Cancelled through enterprise console after explicit confirmation"},
        });
      } else {
        await api(`/api/v1/data-subject-requests/${retry.dataset.id}/retry`, {
          method: "POST",
          headers: {"Idempotency-Key": crypto.randomUUID()},
        });
      }
      toast("数据请求状态已更新");
      await refreshDataRequests();
    } catch (error) { toast(errorMessage(error), "error"); }
  });

  $("#reviewStatus").addEventListener("change", loadReviews);
  $("#reviewCaseList").addEventListener("click", async (event) => {
    const item = event.target.closest(".review-case");
    if (!item) return;
    try { await loadReviewDetail(item.dataset.id); } catch (error) { toast(errorMessage(error), "error"); }
  });
  $("#reviewDetail").addEventListener("submit", async (event) => {
    event.preventDefault();
    const assign = event.target.closest("#assignReviewForm");
    const decision = event.target.closest("#decisionReviewForm");
    try {
      if (assign) {
        await api(`/api/v1/review-cases/${state.selectedReviewId}/assign`, {
          method: "POST",
          body: {principal_id: assign.elements.principal_id.value.trim()},
        });
        toast("复核案例已分配");
      }
      if (decision) {
        const confirmed = await confirmAction({
          title: "提交最终人工决定",
          message: "决定会写入不可变复核事件，并影响该案例的最终状态。",
          phrase: "DECIDE",
        });
        if (!confirmed) return;
        await api(`/api/v1/review-cases/${state.selectedReviewId}/decisions`, {
          method: "POST",
          body: {
            decision: decision.elements.decision.value,
            reason: decision.elements.reason.value,
          },
        });
        toast("人工决定已提交");
      }
      await loadReviews();
      await loadReviewDetail(state.selectedReviewId);
    } catch (error) { toast(errorMessage(error), "error"); }
  });
}

async function initialize() {
  bindEvents();
  roles.forEach((role) => $("#memberForm [name=role]").append(new Option(role, role)));
  try {
    const me = await api("/api/v1/me", {organizationScoped: false});
    state.authMethod = me.authentication?.method || "unknown";
    state.principal = me.principal;
    state.organizations = me.organizations || [];
    if (isOidcAuthMethod(state.authMethod) && !state.principal) {
      showLoginRequired();
      return;
    }
    if (isOidcAuthMethod(state.authMethod)) {
      $("#authBadge").textContent = state.principal.display_name;
      $("#authBadge").className = "status-badge success";
      $("#logoutButton").classList.remove("hidden");
      if (!state.organizations.length) {
        $("#loginRequired").classList.remove("hidden");
        $("#loginRequired h1").textContent = "没有可访问的组织";
        $("#loginRequired p").textContent = "请联系组织管理员为当前账号分配成员资格。";
        $("#loginRequired a").classList.add("hidden");
        return;
      }
      const remembered = localStorage.getItem("ai-examiner.organization");
      const selected = state.organizations.some((item) => item.id === remembered)
        ? remembered
        : state.organizations[0].id;
      populateOrganizationSelect();
      await activateOrganization(selected);
      return;
    }
    $("#authBadge").textContent = "开发模式";
    $("#authBadge").className = "status-badge warning";
    $("#developerAccess").classList.remove("hidden");
    $("#developerOrganizationId").value = localStorage.getItem("ai-examiner.organization") || "";
    $("#developerPrincipalId").value = localStorage.getItem("ai-examiner.dev-principal") || "";
    if ($("#developerOrganizationId").value && $("#developerPrincipalId").value) {
      state.organizations = [{
        id: $("#developerOrganizationId").value,
        display_name: $("#developerOrganizationId").value,
      }];
      await activateOrganization($("#developerOrganizationId").value);
    } else {
      populateOrganizationSelect();
    }
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      showLoginRequired();
      return;
    }
    toast(errorMessage(error), "error");
    $("#authBadge").textContent = "身份服务异常";
    $("#authBadge").className = "status-badge danger";
  }
}

initialize();
