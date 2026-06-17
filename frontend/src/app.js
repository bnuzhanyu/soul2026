import "./styles.css";

const STORAGE_KEY = "jomo-demo-state-v4";
const state = {
  tab: "jomo",
  skills: [],
  agentSkills: [],
  profile: { username: "", displayName: "", goal: "每天轻松练一点" },
  partners: [],
  activePartnerId: "",
  selectedSkillId: "",
  debug: false,
  debugEvents: [],
};

const $ = (selector) => document.querySelector(selector);
let syncTimer = null;
const els = {
  tabButtons: document.querySelectorAll("[data-tab]"),
  tabViews: document.querySelectorAll("[data-view]"),
  loginLabel: $("#loginLabel"),
  loginModal: $("#loginModal"),
  loginForm: $("#loginForm"),
  loginUsernameInput: $("#loginUsernameInput"),
  usernameInput: $("#usernameInput"),
  displayNameInput: $("#displayNameInput"),
  goalInput: $("#goalInput"),
  profileForm: $("#profileForm"),
  partnerList: $("#partnerList"),
  addPartnerButton: $("#addPartnerButton"),
  partnerModal: $("#partnerModal"),
  partnerForm: $("#partnerForm"),
  skillOptions: $("#skillOptions"),
  customSkillTitle: $("#customSkillTitle"),
  customSkillLevel: $("#customSkillLevel"),
  createCustomSkillButton: $("#createCustomSkillButton"),
  partnerNameInput: $("#partnerNameInput"),
  chatAvatar: $("#chatAvatar"),
  chatTitle: $("#chatTitle"),
  chatSubtitle: $("#chatSubtitle"),
  chatStream: $("#chatStream"),
  chatForm: $("#chatForm"),
  messageInput: $("#messageInput"),
  imageInput: $("#imageInput"),
  goalTimeline: $("#goalTimeline"),
  planProgress: $("#planProgress"),
  evidenceCount: $("#evidenceCount"),
  evidenceList: $("#evidenceList"),
  globalSkillTree: $("#globalSkillTree"),
  completeGoalButton: $("#completeGoalButton"),
  skipGoalButton: $("#skipGoalButton"),
  resetButton: $("#resetButton"),
  debugToggle: $("#debugToggle"),
  debugPanel: $("#debugPanel"),
  debugLog: $("#debugLog"),
  clearDebugButton: $("#clearDebugButton"),
  openAdminButton: $("#openAdminButton"),
  backFromAdminButton: $("#backFromAdminButton"),
  adminPage: $("#adminPage"),
  workspace: $("#workspace"),
  adminForm: $("#adminForm"),
  adminSkillSelect: $("#adminSkillSelect"),
  adminAgentSkillList: $("#adminAgentSkillList"),
  adminPlanInput: $("#adminPlanInput"),
};

init();

async function init() {
  loadState();
  bindEvents();
  await loadSkills();
  if (state.profile.username) await loadPartnersFromServer();
  render();
  if (!state.profile.username) els.loginModal.showModal();
  if (state.profile.username && !state.partners.length) await createPartner(state.skills[0]?.id);
}

async function loadSkills() {
  const response = await fetch("/api/skills");
  const data = await response.json();
  state.skills = data.skills || [];
  state.agentSkills = data.agentSkills || [];
  if (!state.selectedSkillId && state.skills[0]) state.selectedSkillId = state.skills[0].id;
}

async function loadPartnersFromServer() {
  const response = await fetch(`/api/users/${encodeURIComponent(state.profile.username)}/partners`);
  if (!response.ok) return;
  const data = await response.json();
  if (Array.isArray(data.partners)) {
    state.partners = data.partners;
    state.activePartnerId = state.activePartnerId && state.partners.some((item) => item.id === state.activePartnerId)
      ? state.activePartnerId
      : state.partners[0]?.id || "";
  }
}

function loadState() {
  try {
    Object.assign(state, JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"));
  } catch {
    localStorage.removeItem(STORAGE_KEY);
  }
}

function saveState() {
  const { skills, agentSkills, debugEvents, ...persisted } = state;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted));
  queuePartnerSync();
}

function queuePartnerSync() {
  if (!state.profile.username) return;
  clearTimeout(syncTimer);
  syncTimer = setTimeout(syncPartnersNow, 280);
}

async function syncPartnersNow() {
  if (!state.profile.username) return;
  try {
    await fetch(`/api/users/${encodeURIComponent(state.profile.username)}/partners`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ partners: state.partners }),
    });
  } catch (error) {
    logEvent("store.sync.error", { message: String(error) });
  }
}

function bindEvents() {
  els.tabButtons.forEach((button) => button.addEventListener("click", () => switchTab(button.dataset.tab)));
  els.loginForm.addEventListener("submit", login);
  els.profileForm.addEventListener("submit", saveProfile);
  els.addPartnerButton.addEventListener("click", () => {
    renderSkillPicker();
    els.partnerNameInput.value = `${findSkill(state.selectedSkillId)?.name || "JOMO"}伙伴`;
    els.partnerModal.showModal();
  });
  els.partnerForm.addEventListener("submit", async (event) => {
    if (event.submitter?.value === "cancel") return;
    event.preventDefault();
    await createPartner(state.selectedSkillId, els.partnerNameInput.value);
    els.partnerModal.close();
  });
  els.createCustomSkillButton.addEventListener("click", createCustomSkill);
  els.chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = els.messageInput.value.trim();
    els.messageInput.value = "";
    sendUserText(text);
  });
  els.imageInput.addEventListener("change", () => {
    const file = els.imageInput.files?.[0];
    els.imageInput.value = "";
    if (file) sendUserMedia(file);
  });
  els.completeGoalButton.addEventListener("click", () => sendUserText("完成当前小目标"));
  els.skipGoalButton.addEventListener("click", goToNextGoal);
  els.resetButton.addEventListener("click", () => sendUserText("重置训练上下文"));
  els.debugToggle.addEventListener("change", () => {
    state.debug = els.debugToggle.checked;
    saveState();
    renderDebug();
  });
  els.clearDebugButton.addEventListener("click", () => {
    state.debugEvents = [];
    saveState();
    renderDebug();
  });
  els.openAdminButton.addEventListener("click", openAdmin);
  els.backFromAdminButton.addEventListener("click", () => switchTab("jomo"));
  els.adminSkillSelect.addEventListener("change", fillAdminPlan);
  els.adminForm.addEventListener("submit", saveAdminPlan);
}

async function login(event) {
  event.preventDefault();
  const username = els.loginUsernameInput.value.trim();
  const response = await fetch("/api/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username }),
  });
  const data = await response.json();
  if (!response.ok) return alert(data.error || "用户名格式不对");
  state.profile = data.user.profile;
  state.partners = data.user.partners || [];
  state.activePartnerId = state.partners[0]?.id || "";
  saveState();
  els.loginModal.close();
  if (!state.partners.length) await createPartner(state.skills[0]?.id);
  render();
}

async function saveProfile(event) {
  event.preventDefault();
  const username = els.usernameInput.value.trim();
  const profile = {
    displayName: els.displayNameInput.value.trim() || username,
    goal: els.goalInput.value.trim() || "每天轻松练一点",
  };
  const response = await fetch("/api/profile", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, profile }),
  });
  const data = await response.json();
  if (!response.ok) return alert(data.error || "保存失败");
  state.profile = data.user.profile;
  saveState();
  render();
}

function render() {
  renderTabs();
  renderProfile();
  renderPartners();
  renderWorkspace();
  renderGlobalSkillTree();
  renderDebug();
}

function switchTab(tab) {
  state.tab = tab;
  saveState();
  render();
}

function renderTabs() {
  els.tabButtons.forEach((button) => button.classList.toggle("active", button.dataset.tab === state.tab));
  els.tabViews.forEach((view) => view.classList.toggle("hidden", view.dataset.view !== state.tab));
  els.workspace.classList.toggle("hidden", state.tab === "admin");
  els.adminPage.classList.toggle("hidden", state.tab !== "admin");
}

function renderProfile() {
  els.loginLabel.textContent = state.profile.username ? `${state.profile.username} · 本地缓存` : "本地登录";
  els.usernameInput.value = state.profile.username || "";
  els.displayNameInput.value = state.profile.displayName || "";
  els.goalInput.value = state.profile.goal || "";
}

function renderPartners() {
  els.partnerList.innerHTML = "";
  if (!state.partners.length) {
    els.partnerList.innerHTML = `<div class="empty-note">还没有伙伴，先点 + 创建一个。</div>`;
    return;
  }
  state.partners.forEach((partner) => {
    const skill = findSkill(partner.skillId);
    const button = document.createElement("button");
    button.className = `partner-item ${partner.id === state.activePartnerId ? "active" : ""}`;
    button.type = "button";
    button.innerHTML = `
      <img src="${skill?.image || ""}" alt="" />
      <span><strong>${escapeHtml(partner.name)}</strong><small>${skill?.name || "技能"} · ${(skill?.tags || []).join(" / ")}</small></span>
    `;
    button.addEventListener("click", () => {
      state.activePartnerId = partner.id;
      switchTab("jomo");
    });
    els.partnerList.appendChild(button);
  });
}

function renderWorkspace() {
  const partner = activePartner();
  const skill = partner ? findSkill(partner.skillId) : null;
  const disabled = !partner;
  [els.completeGoalButton, els.skipGoalButton, els.resetButton, els.messageInput].forEach((item) => (item.disabled = disabled));
  if (!partner || !skill) {
    els.chatTitle.textContent = "选择一个伙伴";
    els.chatSubtitle.textContent = "JOMO 会在这里陪你练";
    els.chatStream.innerHTML = `<div class="empty-chat">创建或选择一个 JOMO 伙伴。</div>`;
    els.planProgress.textContent = "0/0";
    els.evidenceCount.textContent = "0";
    els.goalTimeline.innerHTML = `<div class="empty-note">创建伙伴后开始。</div>`;
    els.evidenceList.innerHTML = `<div class="empty-note">还没有成长证据。</div>`;
    return;
  }
  els.chatAvatar.textContent = skill.name.slice(0, 1);
  els.chatAvatar.style.backgroundImage = `url("${skill.image}")`;
  els.chatTitle.textContent = partner.name;
  els.chatSubtitle.textContent = `${skill.name} · ${(skill.tags || []).join(" / ")}`;
  const all = allMilestones(skill);
  const done = new Set(partner.progress.completedMilestones || []);
  const skipped = new Set(partner.progress.skippedMilestones || []);
  els.planProgress.textContent = `${done.size + skipped.size}/${all.length}`;
  renderGoalTimeline(partner, skill);
  els.evidenceCount.textContent = partner.evidence.length;
  renderEvidenceTimeline(partner);
  renderMessages(partner);
}

function renderGoalTimeline(partner, skill) {
  const nodes = allTimelineNodes(skill);
  if (!nodes.length) {
    els.goalTimeline.innerHTML = `<div class="empty-note">还没有关卡计划。</div>`;
    return;
  }
  const completed = new Set(partner.progress.completedMilestones || []);
  const skipped = new Set(partner.progress.skippedMilestones || []);
  const current = nextMilestone(partner, skill);
  els.goalTimeline.innerHTML = nodes.map((node) => {
    const status = completed.has(node.id) ? "done" : skipped.has(node.id) ? "skipped" : current?.id === node.id ? "current" : "upcoming";
    const mark = status === "done" ? "✓" : status === "skipped" ? "跳" : status === "current" ? "●" : "";
    const label = status === "done" ? "已完成" : status === "skipped" ? "已跳过" : status === "current" ? "进行中" : "未开始";
    return `
      <div class="timeline-item goal-item ${status}">
        <div class="timeline-mark">${escapeHtml(mark)}</div>
        <div class="timeline-content">
          <small>${escapeHtml(node.goalTitle)} · ${escapeHtml(label)}</small>
          <strong>${escapeHtml(node.title)}</strong>
          <p>${escapeHtml(node.description || "")}</p>
        </div>
      </div>
    `;
  }).join("");
}

function renderEvidenceTimeline(partner) {
  const items = [...(partner.evidence || [])]
    .sort((a, b) => Number(a.at || 0) - Number(b.at || 0))
    .slice(-12);
  els.evidenceList.innerHTML = items.map((item) => `
    <div class="timeline-item evidence-item done">
      <div class="timeline-mark">✓</div>
      <div class="timeline-content">
        <small>${escapeHtml(formatLocalTime(item.at || Date.now()))}</small>
        <p>${escapeHtml(item.content || "完成了一次练习")}</p>
      </div>
    </div>
  `).join("") || `<div class="empty-note">还没有成长证据。</div>`;
}

function renderMessages(partner) {
  els.chatStream.innerHTML = "";
  partner.messages.forEach((message) => appendMessageNode(message));
  els.chatStream.scrollTop = els.chatStream.scrollHeight;
}

function appendMessageNode(message) {
  const row = document.createElement("div");
  row.className = `message-row ${message.role}`;
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  if (message.type === "image") {
    bubble.innerHTML = `<img src="${message.url}" alt="上传图片" /><p>${escapeHtml(message.content)}</p>`;
  } else if (message.type === "audio") {
    bubble.innerHTML = `<audio controls src="${escapeAttribute(message.url)}"></audio><p>${escapeHtml(message.content || "音频练习素材")}</p>`;
  } else if (message.type === "html") {
    bubble.classList.add("rich-html");
    bubble.innerHTML = sanitizeHtml(message.content);
    hydrateGeneratedUi(bubble);
  } else if (message.type === "markdown") {
    bubble.classList.add("markdown-bubble");
    bubble.innerHTML = renderMarkdown(message.content);
  } else {
    bubble.textContent = message.content;
  }
  row.appendChild(bubble);
  els.chatStream.appendChild(row);
}

function renderGlobalSkillTree() {
  const partner = activePartner();
  const skill = partner ? findSkill(partner.skillId) : state.skills[0];
  if (!skill) return;
  const completed = new Set(partner?.progress?.completedMilestones || []);
  const skipped = new Set(partner?.progress?.skippedMilestones || []);
  els.globalSkillTree.innerHTML = (skill.plan?.goals || []).map((goal) => `
    <div class="goal-block">
      <h3>${escapeHtml(goal.title)} <small>${escapeHtml(goal.days)}</small></h3>
      <p>${escapeHtml(goal.outcome)}</p>
      ${(goal.milestones || []).map((m) => `
        <button class="tree-node ${completed.has(m.id) ? "done" : skipped.has(m.id) ? "skipped" : ""}" data-node="${m.id}">
          <span>${completed.has(m.id) ? "✓" : skipped.has(m.id) ? "↷" : "·"}</span>
          <strong>${escapeHtml(m.title)}</strong>
          <small>${escapeHtml(m.description)}</small>
        </button>
      `).join("")}
    </div>
  `).join("");
  els.globalSkillTree.querySelectorAll("[data-node]").forEach((button) => {
    button.addEventListener("click", () => resetToMilestone(button.dataset.node));
  });
}

function renderSkillPicker() {
  els.skillOptions.innerHTML = "";
  state.skills.forEach((skill) => {
    const button = document.createElement("button");
    button.className = `skill-option ${skill.id === state.selectedSkillId ? "active" : ""}`;
    button.type = "button";
    button.innerHTML = `<img src="${skill.image}" alt="" /><span><strong>${skill.name}</strong><small>${(skill.tags || []).join(" / ")}</small></span>`;
    button.addEventListener("click", () => {
      state.selectedSkillId = skill.id;
      els.partnerNameInput.value = `${skill.name}伙伴`;
      renderSkillPicker();
    });
    els.skillOptions.appendChild(button);
  });
}

async function createPartner(skillId, customName = "") {
  if (!skillId) return;
  const skill = findSkill(skillId);
  const response = await fetch("/api/partners/plan", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ skillId, profile: state.profile }),
  });
  const plan = await response.json();
  const first = allMilestones(skill)[0];
  const partner = {
    id: `partner-${Date.now()}`,
    sessionId: crypto.randomUUID?.() || `session-${Date.now()}`,
    name: customName.trim() || `${skill.name}伙伴`,
    skillId,
    plan,
    progress: { completedMilestones: [], skippedMilestones: [], currentMilestoneId: first?.id || "" },
    evidence: [],
    compacts: [],
    messages: [createStartLearningMessage(skill, plan, first, { intro: "新的 JOMO 伙伴准备好啦。" })],
  };
  state.partners.unshift(partner);
  state.activePartnerId = partner.id;
  logEvent("partner.created", { partner });
  saveState();
  render();
}

function createStartLearningMessage(skill, plan, milestone, options = {}) {
  const title = milestone?.title || plan.challenge || skill.starter || "今天的小练习";
  const description = milestone?.description || plan.reason || skill.starter || "准备好后，我会生成这次的学习内容。";
  const intro = options.intro || "准备好后，我会把这一关拆成一个很小的练习。";
  return {
    role: "assistant",
    type: "html",
    content: `
      <div class="choice-card start-card">
        <strong>${escapeHtml(intro)}</strong>
        <p>${escapeHtml(title)} · ${escapeHtml(description)}</p>
        <button data-jomo-choice="开始本关卡">开始本关卡</button>
      </div>
    `,
  };
}

async function createCustomSkill() {
  const title = els.customSkillTitle.value.trim();
  if (!title) return els.customSkillTitle.focus();
  const response = await fetch("/api/skills/custom", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username: state.profile.username, title, targetLevel: els.customSkillLevel.value.trim(), tags: ["自定义"] }),
  });
  const data = await response.json();
  state.skills.push(data.skill);
  state.selectedSkillId = data.skill.id;
  logEvent("skill.custom.created", { prompt: data.skill.promptForAgent, skill: data.skill });
  renderSkillPicker();
}

async function sendUserText(text) {
  const partner = activePartner();
  if (!partner || !text) return;
  partner.messages.push({ role: "user", type: "text", content: text });
  saveState();
  renderWorkspace();
  await streamAssistantReply(partner, text);
}

async function sendUserMedia(file) {
  const partner = activePartner();
  if (!partner) return;
  const dataUrl = await fileToDataUrl(file);
  const mediaType = file.type.startsWith("audio/") ? "audio" : "image";
  let upload = null;
  try {
    upload = await uploadMedia({ dataUrl, file, mediaType });
  } catch (error) {
    alert(`上传失败：${String(error.message || error)}`);
    logEvent("upload.error", { message: String(error.message || error), filename: file.name });
    return;
  }
  const content = mediaType === "audio" ? "这是我的练习音频，帮我听感反馈一下。" : "这是我的练习图片，帮我按目标打个分。";
  partner.messages.push({ role: "user", type: mediaType, url: upload.url, content, oss: upload });
  saveState();
  renderWorkspace();
  await streamAssistantReply(partner, mediaType === "audio" ? "用户上传了一段练习音频，请根据目标进行简短反馈。" : "用户上传了一张练习图片，请根据目标进行简短评分。", {
    type: mediaType,
    filename: file.name,
    size: file.size,
    contentType: file.type,
    url: upload.url,
    ossUri: upload.ossUri,
  });
}

async function uploadMedia({ dataUrl, file, mediaType }) {
  const response = await fetch("/api/uploads", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      username: state.profile.username,
      filename: file.name,
      mediaType,
      dataUrl,
    }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "OSS 上传失败");
  return data.upload;
}

async function streamAssistantReply(partner, userText, attachment = null) {
  const assistant = { role: "assistant", type: "text", content: "" };
  partner.messages.push(assistant);
  renderWorkspace();
  const bubble = els.chatStream.querySelector(".message-row.assistant:last-child .message-bubble");
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ profile: state.profile, partner, userText, attachment }),
  });
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) handleSse(part, partner, assistant, bubble);
  }
  if (!assistant.content.trim()) {
    partner.messages = partner.messages.filter((message) => message !== assistant);
  }
  compactIfNeeded(partner);
  saveState();
  render();
}

function handleSse(raw, partner, assistant, bubble) {
  const eventLine = raw.split("\n").find((line) => line.startsWith("event: "));
  const dataLine = raw.split("\n").find((line) => line.startsWith("data: "));
  if (!eventLine || !dataLine) return;
  const type = eventLine.replace("event: ", "").trim();
  const data = JSON.parse(dataLine.replace("data: ", ""));
  logEvent(type, data);
  if (type === "token") {
    assistant.content += data.text;
    bubble.textContent = assistant.content;
    els.chatStream.scrollTop = els.chatStream.scrollHeight;
  }
  if (type === "html") {
    partner.messages.push({ role: "assistant", type: "html", content: data.html });
    renderWorkspace();
  }
  if (type === "markdown") {
    partner.messages.push({ role: "assistant", type: "markdown", content: data.markdown });
    renderWorkspace();
  }
  if (type === "image") {
    partner.messages.push({ role: "assistant", type: "image", url: data.url, content: "生成了一张练习素材图。" });
    renderWorkspace();
  }
  if (type === "audio") {
    partner.messages.push({ role: "assistant", type: "audio", url: data.url, content: "生成了一段音频练习素材。" });
    renderWorkspace();
  }
  if (type === "progress") applyProgress(partner, data);
  if (type === "compact") partner.compacts.unshift(data);
}

function applyProgress(partner, data) {
  if (data.evidence) partner.evidence.unshift({ id: `e-${Date.now()}`, content: data.evidence, at: Date.now() });
  if (data.completeNext || data.action === "completeNext") completeNext(partner);
  if (data.action === "skipNext") skipNext(partner);
  if (data.resetContext) resetConversation(partner);
}

function goToNextGoal() {
  const partner = activePartner();
  if (!partner) return;
  skipNext(partner, { source: "button" });
  saveState();
  render();
}

function completeNext(partner, options = {}) {
  const skill = findSkill(partner.skillId);
  const next = nextMilestone(partner, skill);
  if (!next) return;
  partner.progress.completedMilestones.push(next.id);
  partner.progress.currentMilestoneId = nextMilestone(partner, skill)?.id || "";
  rotateSession(partner, "complete");
  appendCurrentGoalPrompt(partner, skill, {
    notice: options.notice || "这一关盖章啦。我们去看看下一关卡。",
    emptyNotice: "这套关卡已经走完啦，可以去成就页回看一下小脚印。",
  });
}

function skipNext(partner, options = {}) {
  const skill = findSkill(partner.skillId);
  const next = nextMilestone(partner, skill);
  if (!next) return;
  partner.progress.skippedMilestones.push(next.id);
  partner.progress.currentMilestoneId = nextMilestone(partner, skill)?.id || "";
  rotateSession(partner, "skip");
  appendCurrentGoalPrompt(partner, skill, {
    notice: options.notice || "进入下一关卡。刚刚那关先放进小口袋，继续往前走一点点。",
    emptyNotice: "已经到最后啦，没有新的关卡可以前进了。",
  });
}

function resetConversation(partner) {
  const skill = findSkill(partner.skillId);
  partner.compacts.unshift({ at: Date.now(), action: "reset", summary: `重置到 ${nextMilestone(partner, skill)?.title || "当前目标"}`, progress: partner.progress });
  rotateSession(partner, "reset");
  appendCurrentGoalPrompt(partner, skill, {
    notice: "已重置到当前关卡。我们从这一步重新轻轻开始。",
    emptyNotice: "当前没有可开始的关卡。",
  });
}

function appendCurrentGoalPrompt(partner, skill, { notice, emptyNotice } = {}) {
  const milestone = nextMilestone(partner, skill);
  const text = milestone
    ? `${notice || "进入当前关卡。"}\n当前关卡：${milestone.title}`
    : (emptyNotice || "当前没有可开始的关卡。");
  partner.messages.push({ role: "assistant", type: "text", content: text });
  if (milestone) {
    partner.messages.push(createStartLearningMessage(skill, partner.plan || {}, milestone, {
      intro: "要开始这一关吗？",
    }));
  }
}

function compactIfNeeded(partner) {
  if (partner.messages.length <= 18) return;
  partner.compacts.unshift({ at: Date.now(), action: "auto", summary: partner.messages.slice(0, -8).map((m) => `${m.role}:${m.content || m.type}`).join(" / ").slice(0, 500), progress: partner.progress });
}

function rotateSession(partner, action) {
  partner.compacts.unshift({ at: Date.now(), action, summary: `${action} 后开启新 session`, progress: partner.progress });
  partner.sessionId = crypto.randomUUID?.() || `session-${Date.now()}`;
}

function resetToMilestone(id) {
  const partner = activePartner();
  if (!partner) return;
  partner.progress.currentMilestoneId = id;
  resetConversation(partner);
  saveState();
  render();
}

function hydrateGeneratedUi(root) {
  root.querySelectorAll("[data-jomo-choice]").forEach((button) => button.addEventListener("click", () => sendUserText(button.getAttribute("data-jomo-choice"))));
  hydrateReadingCard(root);
}

function hydrateReadingCard(root) {
  const card = root.querySelector("[data-reading-seconds]");
  if (!card || card.dataset.bound === "1") return;
  card.dataset.bound = "1";
  const seconds = Number(card.dataset.readingSeconds);
  const countdownEl = card.querySelector("[data-reading-countdown]");
  const textEl = card.querySelector("[data-reading-text]");
  let remaining = seconds;
  let timer = null;
  const stop = () => timer && clearInterval(timer);
  const visible = (yes) => textEl?.classList.toggle("is-hidden", !yes);
  const start = () => {
    stop();
    remaining = seconds;
    visible(false);
    let n = 3;
    countdownEl.textContent = n;
    timer = setInterval(() => {
      n -= 1;
      if (n > 0) return (countdownEl.textContent = n);
      stop();
      visible(true);
      countdownEl.textContent = `${remaining}s`;
      timer = setInterval(() => {
        remaining -= 1;
        countdownEl.textContent = remaining > 0 ? `${remaining}s` : "答题";
        if (remaining <= 0) {
          stop();
          visible(false);
        }
      }, 1000);
    }, 700);
  };
  card.querySelectorAll("[data-reading-action]").forEach((button) => button.addEventListener("click", () => {
    const action = button.dataset.readingAction;
    if (action === "start" || action === "restart") start();
    if (action === "pause") { stop(); visible(false); countdownEl.textContent = "暂停"; }
    if (action === "reveal") { stop(); visible(true); countdownEl.textContent = "显示中"; }
  }));
}

function openAdmin() {
  els.adminSkillSelect.innerHTML = state.skills.map((skill) => `<option value="${skill.id}">${escapeHtml(skill.name)}</option>`).join("");
  fillAdminPlan();
  switchTab("admin");
}

function fillAdminPlan() {
  const skill = findSkill(els.adminSkillSelect.value || state.skills[0]?.id);
  els.adminPlanInput.value = JSON.stringify(stripRuntimeSkillFields(skill || {}), null, 2);
  renderAgentSkillChecks(skill);
}

async function saveAdminPlan(event) {
  event.preventDefault();
  try {
    const skill = JSON.parse(els.adminPlanInput.value);
    skill.agentSkills = [...els.adminAgentSkillList.querySelectorAll("input:checked")].map((item) => item.value);
    const response = await fetch("/api/admin/skills", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ skillId: els.adminSkillSelect.value, skill }),
    });
    const data = await response.json();
    if (!response.ok) return alert(data.error || "保存失败");
    state.skills = state.skills.map((skill) => (skill.id === data.skill.id ? data.skill : skill));
    fillAdminPlan();
    render();
  } catch {
    alert("学习技能 JSON 格式不对");
  }
}

function renderAgentSkillChecks(skill) {
  const selected = new Set(skill?.agentSkills || []);
  els.adminAgentSkillList.innerHTML = state.agentSkills.map((item) => `
    <label class="agent-skill-check">
      <input type="checkbox" value="${escapeAttribute(item.id)}" ${selected.has(item.id) ? "checked" : ""} />
      <span>${escapeHtml(item.name)}</span>
    </label>
  `).join("") || `<p>还没有 agent skill。把 SKILL.md 文件夹放到 backend/agent_skills 下即可。</p>`;
}

function stripRuntimeSkillFields(skill) {
  const copy = { ...skill };
  delete copy._path;
  return copy;
}

function logEvent(type, data) {
  const tail = state.debugEvents[state.debugEvents.length - 1];
  if (tail && canMergeDebug(tail.type, type)) {
    tail.at = new Date().toISOString();
    if (type === "token") tail.data.text = `${tail.data.text || ""}${data.text || ""}`;
    else if (type === "agent.assistant_text") tail.data.text = `${tail.data.text || ""}${data.text || ""}`;
    else tail.data.items = [...(tail.data.items || []), data];
    if (state.debug) renderDebug();
    return;
  }
  state.debugEvents.push({ at: new Date().toISOString(), type, data });
  state.debugEvents = state.debugEvents.slice(-120);
  if (state.debug) renderDebug();
}

function canMergeDebug(previous, next) {
  return (previous === "token" && next === "token") || (previous === "agent.assistant_text" && next === "agent.assistant_text");
}

function renderDebug() {
  els.debugPanel.classList.toggle("hidden", !state.debug);
  els.debugToggle.checked = state.debug;
  els.debugLog.innerHTML = state.debugEvents.map((event) => `
    <details class="debug-item ${debugClass(event.type)}" open>
      <summary>${debugSummary(event)}</summary>
      ${debugBody(event)}
    </details>
  `).join("");
}

function debugSummary(event) {
  const time = formatLocalTime(event.at);
  if (event.type === "agent.tool_use") {
    const name = event.data?.input?.skill || event.data?.name || "工具";
    return `${escapeHtml(debugLabel(event.type))} · ${escapeHtml(name)} <small>${time}</small>`;
  }
  if (event.type === "agent.tool_result") {
    const ok = event.data?.isError ? "失败" : "成功";
    return `${escapeHtml(debugLabel(event.type))} · ${escapeHtml(ok)} <small>${time}</small>`;
  }
  return `${escapeHtml(debugLabel(event.type))} <small>${time}</small>`;
}

function debugBody(event) {
  if (event.type === "agent.tool_result") return renderToolResultDebug(event.data);
  if (event.type === "agent.tool_use") return renderToolUseDebug(event.data);
  return `<pre>${escapeHtml(JSON.stringify(event.data, null, 2))}</pre>`;
}

function renderToolUseDebug(data = {}) {
  const input = data.input || {};
  const parsed = input.parsedArgs ? `<div class="debug-subtitle">parsed args</div><pre>${escapeHtml(JSON.stringify(input.parsedArgs, null, 2))}</pre>` : "";
  return `
    <div class="debug-meta">
      <span>${escapeHtml(debugLabel("agent.tool_use"))}</span>
      <span>${escapeHtml(data.name || "tool")}</span>
      ${input.skill ? `<span>${escapeHtml(input.skill)}</span>` : ""}
      ${input.argsFormat ? `<span>args: ${escapeHtml(input.argsFormat)}</span>` : ""}
    </div>
    <div class="debug-subtitle">raw input</div>
    <pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>
    ${parsed}
  `;
}

function renderToolResultDebug(data = {}) {
  const content = data.content || {};
  const parsed = content.parsed ? `<div class="debug-subtitle">parsed result</div><pre>${escapeHtml(JSON.stringify(content.parsed, null, 2))}</pre>` : "";
  return `
    <div class="debug-meta">
      <span>${escapeHtml(debugLabel("agent.tool_result"))}</span>
      <span>${data.isError ? "失败" : "成功"}</span>
      ${data.toolUseId ? `<span>${escapeHtml(data.toolUseId)}</span>` : ""}
      ${content.truncated ? "<span>truncated</span>" : ""}
    </div>
    ${parsed}
    <div class="debug-subtitle">text</div>
    <pre>${escapeHtml(content.text || JSON.stringify(data, null, 2))}</pre>
  `;
}

function debugLabel(type) {
  const labels = {
    "agent.started": "AI 开始回复",
    "agent.session": "会话准备",
    "agent.thinking": "模型思考",
    "agent.tool_use": "工具调用",
    "agent.tool_result": "工具结果",
    "agent.assistant_text": "模型原始文本",
    "agent.result": "模型结束",
    "agent.error": "AI 错误",
    "token": "流式回复",
    "html": "HTML 卡片",
    "markdown": "Markdown 卡片",
    "image": "图片输出",
    "audio": "音频输出",
    "progress": "进度更新",
    "compact": "上下文整理",
    "ai.raw": "完整输出",
    "done": "请求完成",
    "upload.error": "上传错误",
    "store.sync.error": "同步错误",
    "partner.created": "创建伙伴",
    "skill.custom.created": "创建学习技能",
  };
  return labels[type] || type;
}

function formatLocalTime(value) {
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(new Date(value)).reduce((acc, part) => {
    acc[part.type] = part.value;
    return acc;
  }, {});
  return `${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

function debugClass(type) {
  if (type.includes("thinking")) return "thinking";
  if (type === "agent.tool_result") return "tool-result";
  if (type.includes("tool")) return "tool";
  if (type.includes("error")) return "error";
  if (type.includes("raw") || type.includes("assistant_text")) return "raw";
  return "normal";
}

function activePartner() {
  return state.partners.find((item) => item.id === state.activePartnerId) || null;
}

function findSkill(id) {
  return state.skills.find((skill) => skill.id === id) || null;
}

function allMilestones(skill) {
  return (skill?.plan?.goals || []).flatMap((goal) => goal.milestones || []);
}

function allTimelineNodes(skill) {
  return (skill?.plan?.goals || []).flatMap((goal) => (goal.milestones || []).map((milestone) => ({
    ...milestone,
    goalId: goal.id || "",
    goalTitle: goal.title || "阶段",
  })));
}

function nextMilestone(partner, skill) {
  const done = new Set([...(partner.progress.completedMilestones || []), ...(partner.progress.skippedMilestones || [])]);
  return allMilestones(skill).find((item) => !done.has(item.id)) || null;
}

function sanitizeHtml(value) {
  const template = document.createElement("template");
  template.innerHTML = value;
  template.content.querySelectorAll("script,style,iframe,object,embed,link,meta").forEach((node) => node.remove());
  template.content.querySelectorAll("*").forEach((node) => [...node.attributes].forEach((attr) => {
    if (/^on/i.test(attr.name) || /javascript:/i.test(attr.value)) node.removeAttribute(attr.name);
  }));
  return template.innerHTML;
}

function renderMarkdown(value) {
  let html = escapeHtml(value);
  html = html.replace(/^### (.*)$/gm, "<h4>$1</h4>");
  html = html.replace(/^## (.*)$/gm, "<h3>$1</h3>");
  html = html.replace(/^# (.*)$/gm, "<h2>$1</h2>");
  html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/^- (.*)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>[\s\S]*?<\/li>)/g, "<ul>$1</ul>");
  return html.split(/\n{2,}/).map((block) => {
    const trimmed = block.trim();
    if (!trimmed) return "";
    if (/^<(h2|h3|h4|ul)/.test(trimmed)) return trimmed;
    return `<p>${trimmed.replace(/\n/g, "<br>")}</p>`;
  }).join("");
}

function escapeAttribute(text) {
  return escapeHtml(text).replaceAll("'", "&#39;");
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function escapeHtml(text) {
  return String(text ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}
