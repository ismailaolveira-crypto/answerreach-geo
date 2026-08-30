import { PLATFORMS, readEnabledPlatformKeys } from "./platform-data.js";

const PROTOCOL = "geo-article-assistant.v1";

const STATUS_META = {
  checking: { label: "检测中", detail: "正在读取当前浏览器登录状态" },
  logged_in: { label: "已登录", detail: "已识别登录账号" },
  not_logged_in: { label: "未登录", detail: "未在当前浏览器识别到账号" },
  requires_authorization: { label: "需官方授权", detail: "等待平台官方客户端授权" },
  error: { label: "检测失败", detail: "本次无法确认登录状态" },
};

const platformList = document.querySelector("#platformList");
const summaryText = document.querySelector("#summaryText");
const lastChecked = document.querySelector("#lastChecked");
const refreshButton = document.querySelector("#refreshButton");
const managePlatformsButton = document.querySelector("#managePlatformsButton");
const version = document.querySelector("#version");
const approvalCard = document.querySelector("#approvalCard");
const approvalOrigin = document.querySelector("#approvalOrigin");
const approvalCount = document.querySelector("#approvalCount");
const approvalTargets = document.querySelector("#approvalTargets");
const approveApprovalButton = document.querySelector("#approveApprovalButton");
const rejectApprovalButton = document.querySelector("#rejectApprovalButton");
let visiblePlatforms = [];

async function renderPendingApproval() {
  const pending = await send("getPendingDraftApproval").catch(() => null);
  approvalCard.hidden = !pending;
  if (!pending) return;
  approvalOrigin.textContent = `来自 ${pending.sourceOrigin} · 任务 #${pending.runId}`;
  approvalCount.textContent = `${pending.targets.length} 个平台`;
  approvalTargets.replaceChildren(...pending.targets.map((target) => {
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = target.title || "未命名草稿";
    const detail = document.createElement("small");
    detail.textContent = `${target.platformKey} · ${target.accountId}`;
    item.append(title, detail);
    return item;
  }));
}

async function decideApproval(method) {
  approveApprovalButton.disabled = true;
  rejectApprovalButton.disabled = true;
  try {
    await send(method);
    await renderPendingApproval();
    summaryText.textContent = method === "approvePendingDraft" ? "已批准，请回工作台重试写入" : "已拒绝本次草稿任务";
  } finally {
    approveApprovalButton.disabled = false;
    rejectApprovalButton.disabled = false;
  }
}

function send(method) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ protocolVersion: PROTOCOL, method }, (response) => {
      const runtimeError = chrome.runtime.lastError;
      if (runtimeError) {
        reject(new Error(runtimeError.message));
        return;
      }
      if (!response?.ok) {
        reject(new Error(response?.error || "GEO 文章助手连接失败"));
        return;
      }
      resolve(response.data);
    });
  });
}

function currentRows(statuses = []) {
  const byPlatform = new Map(statuses.map((item) => [item.platformKey, item]));
  return visiblePlatforms.map((platform) => ({
    ...platform,
    ...(byPlatform.get(platform.key) || { status: "error" }),
  }));
}

function renderRows(rows) {
  platformList.replaceChildren(...rows.map((row) => {
    const meta = STATUS_META[row.status] || STATUS_META.error;
    const item = document.createElement("li");
    item.className = "platform-row";

    const logoWrap = document.createElement("span");
    logoWrap.className = "platform-logo";
    const logo = document.createElement("img");
    logo.src = row.logo;
    logo.alt = `${row.label} 官方标志`;
    logoWrap.append(logo);

    const copy = document.createElement("div");
    copy.className = "platform-copy";
    const name = document.createElement("p");
    name.className = "platform-name";
    name.textContent = row.label;
    const detail = document.createElement("p");
    detail.className = "platform-detail";
    detail.textContent = row.account?.displayName || row.message || meta.detail;
    copy.append(name, detail);

    const status = document.createElement("span");
    status.className = `status-pill status-${row.status}`;
    status.textContent = meta.label;
    status.setAttribute("aria-label", `${row.label}：${meta.label}`);

    item.append(logoWrap, copy, status);
    return item;
  }));
}

function renderSummary(rows) {
  const loggedIn = rows.filter((item) => item.status === "logged_in").length;
  const pending = rows.length - loggedIn;
  summaryText.textContent = `已登录 ${loggedIn} · 待处理 ${pending}`;
  lastChecked.textContent = "刚刚更新";
}

async function refresh() {
  refreshButton.dataset.loading = "true";
  refreshButton.disabled = true;
  summaryText.textContent = "正在检测当前浏览器…";
  lastChecked.textContent = "";
  const enabledKeys = await readEnabledPlatformKeys();
  const enabledSet = new Set(enabledKeys);
  visiblePlatforms = PLATFORMS.filter((platform) => enabledSet.has(platform.key));
  renderRows(currentRows(visiblePlatforms.map(({ key }) => ({ platformKey: key, status: "checking" }))));
  try {
    const statuses = await send("getPlatformStatuses");
    const rows = currentRows(statuses);
    renderRows(rows);
    renderSummary(rows);
  } catch {
    const rows = currentRows([]);
    renderRows(rows);
    summaryText.textContent = "暂时无法完成检测";
    lastChecked.textContent = "请重试";
  } finally {
    refreshButton.dataset.loading = "false";
    refreshButton.disabled = false;
  }
}

version.textContent = `v${chrome.runtime.getManifest().version}`;
refreshButton.addEventListener("click", refresh);
managePlatformsButton.addEventListener("click", () => chrome.tabs.create({ url: chrome.runtime.getURL("platforms.html") }));
approveApprovalButton.addEventListener("click", () => decideApproval("approvePendingDraft"));
rejectApprovalButton.addEventListener("click", () => decideApproval("rejectPendingDraft"));
Promise.all([refresh(), renderPendingApproval()]);
