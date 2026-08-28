const PROTOCOL = "geo-article-assistant.v1";
const SUPPORTED_PLATFORMS = [
  "wechat", "zhihu", "juejin", "51cto", "csdn", "bilibili", "baijiahao", "weibo", "yuque",
  "douban", "sohu", "xueqiu", "cnblogs", "oschina", "segmentfault", "imooc", "woshipm", "eastmoney",
];
const DEFAULT_ENABLED_PLATFORMS = ["wechat", "zhihu", "juejin", "51cto", "csdn"];
const ENABLED_PLATFORMS_STORE = "geoArticleAssistantEnabledPlatformsV1";
const BUNDLED_PLATFORM_KEYS = new Set([
  "bilibili", "baijiahao", "weibo", "yuque", "douban", "sohu", "xueqiu",
  "cnblogs", "oschina", "segmentfault", "imooc", "woshipm", "eastmoney",
]);
const IMAGE_UPLOAD_PLATFORM_KEYS = new Set([
  "wechat", "zhihu", "juejin", "51cto", ...BUNDLED_PLATFORM_KEYS,
]);
const DRAFT_RECEIPT_STORE = "geoArticleAssistantDraftReceiptsV1";
const MAX_DRAFT_RECEIPTS = 100;
let bundledAdaptersPromise;

function bundledAdapters() {
  bundledAdaptersPromise ||= import(chrome.runtime.getURL("vendor/wechatsync-adapters.js"));
  return bundledAdaptersPromise;
}

function account(platformKey, userId, displayName, avatar = "") {
  return {
    accountId: `${platformKey}:${userId}`,
    platformKey,
    userId: String(userId),
    displayName: displayName || String(userId),
    avatar,
  };
}

async function responseJson(response, fallback) {
  const text = await response.text();
  if (!response.ok) throw new Error(`${fallback}（${response.status}）`);
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`${fallback}：平台返回了无法识别的内容`);
  }
}

function assertTask(task) {
  if (!task || task.protocol_version !== PROTOCOL) throw new Error("任务协议版本不匹配");
  if (!task.task_token || !task.content_fingerprint || !Array.isArray(task.targets)) throw new Error("任务内容不完整");
  if (!Number.isInteger(task.run_id) || task.run_id <= 0 || task.targets.length < 1 || task.targets.length > SUPPORTED_PLATFORMS.length) throw new Error("任务范围不完整");
  if (Date.parse(task.expires_at) <= Date.now()) throw new Error("草稿写入任务已过期，请在 GEO 平台重新发起");
  if (task.targets.some((target) => !SUPPORTED_PLATFORMS.includes(target.platform_key))) throw new Error("任务包含不受支持的平台");
  if (task.targets.some((target) => !target.content_fingerprint)) throw new Error("平台稿缺少内容指纹");
  const platformKeys = task.targets.map((target) => target.platform_key);
  if (new Set(platformKeys).size !== platformKeys.length) throw new Error("同一任务不能重复包含同一平台");
}

function draftReceiptKey(task, target, accountId) {
  const content = JSON.stringify([
    accountId,
    target.title || "",
    target.summary || "",
    target.body_markdown || "",
    target.body_html || "",
  ]);
  let localHash = 2166136261;
  for (let index = 0; index < content.length; index += 1) {
    localHash ^= content.charCodeAt(index);
    localHash = Math.imul(localHash, 16777619);
  }
  return [
    task.run_id,
    task.content_fingerprint,
    target.platform_key,
    target.content_fingerprint,
    (localHash >>> 0).toString(16),
  ].join(":");
}

async function readDraftReceipts() {
  const stored = await chrome.storage.local.get(DRAFT_RECEIPT_STORE);
  return Array.isArray(stored[DRAFT_RECEIPT_STORE]) ? stored[DRAFT_RECEIPT_STORE] : [];
}

async function getDraftReceipt(key) {
  return (await readDraftReceipts()).find((item) => item?.key === key) || null;
}

async function putDraftReceipt(receipt) {
  const rows = (await readDraftReceipts()).filter((item) => item?.key !== receipt.key);
  rows.push(receipt);
  rows.sort((left, right) => Number(left.updatedAt || 0) - Number(right.updatedAt || 0));
  await chrome.storage.local.set({ [DRAFT_RECEIPT_STORE]: rows.slice(-MAX_DRAFT_RECEIPTS) });
}

async function removeDraftReceipt(key) {
  const rows = (await readDraftReceipts()).filter((item) => item?.key !== key);
  await chrome.storage.local.set({ [DRAFT_RECEIPT_STORE]: rows });
}

function assertPortableImages(target) {
  const content = `${target.body_markdown || ""}\n${target.body_html || ""}`;
  const sources = [...content.matchAll(/(?:src=["']|!\[[^\]]*\]\()([^"')\s]+)/gi)].map((match) => match[1]);
  const safeAssistantMedia = /^http:\/\/(?:localhost|127\.0\.0\.1):39003\/api\/geo\/\d+\/distribution-runs\/\d+\/assistant-media\/\d+\?task_token=[A-Za-z0-9_-]{20,200}$/;
  const unsafe = sources.find((source) => !/^https:\/\//i.test(source) && !safeAssistantMedia.test(source));
  if (unsafe) throw new Error("内容包含本地或非 HTTPS 图片，为避免丢图已停止写入");
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function approvedTargetMedia(target) {
  return (Array.isArray(target.image_manifest) ? target.image_manifest : []).filter((item) => (
    item
    && item.review_status === "approved"
    && item.quality_gate === "passed"
    && Number.isInteger(Number(item.artifact_id))
    && typeof item.content_url === "string"
    && /^http:\/\/(?:localhost|127\.0\.0\.1):39003\/api\/geo\//.test(item.content_url)
  ));
}

function insertMarkdownMedia(markdown, media) {
  if (markdown.includes(media.content_url)) return markdown;
  const alt = String(media.alt_text || "文章配图").replace(/[\[\]()]/g, "").trim();
  const caption = String(media.caption || "").trim();
  const block = `![${alt}](${media.content_url})${caption ? `\n\n*图注：${caption}*` : ""}`;
  if (media.placement === "cover") return `${block}\n\n${markdown}`;
  const parts = String(markdown || "").split(/\n{2,}/);
  const sectionMatch = String(media.placement || "").match(/^after_section_(\d+)$/);
  const position = sectionMatch ? Math.min(Number(sectionMatch[1]) * 2, parts.length) : Math.min(1, parts.length);
  parts.splice(position, 0, block);
  return parts.join("\n\n");
}

function insertHtmlMedia(html, media) {
  if (html.includes(media.content_url)) return html;
  const figure = `<figure data-geo-reviewed-media="${Number(media.artifact_id)}"><img src="${escapeHtml(media.content_url)}" alt="${escapeHtml(media.alt_text || "文章配图")}">${media.caption ? `<figcaption>图注：${escapeHtml(media.caption)}</figcaption>` : ""}</figure>`;
  if (media.placement === "cover") return `${figure}${html}`;
  const closingParagraphs = [...String(html || "").matchAll(/<\/p>/gi)];
  const sectionMatch = String(media.placement || "").match(/^after_section_(\d+)$/);
  const desiredIndex = sectionMatch ? Math.max(0, Number(sectionMatch[1])) : 0;
  const match = closingParagraphs[Math.min(desiredIndex, Math.max(0, closingParagraphs.length - 1))];
  if (!match || match.index === undefined) return `${html}${figure}`;
  const offset = match.index + match[0].length;
  return `${html.slice(0, offset)}${figure}${html.slice(offset)}`;
}

function assembleReviewedMedia(target) {
  const media = approvedTargetMedia(target);
  if (!media.length) return { ...target, reviewed_media_count: 0 };
  let markdown = String(target.body_markdown || "");
  let html = String(target.body_html || "");
  for (const item of media) {
    markdown = insertMarkdownMedia(markdown, item);
    html = insertHtmlMedia(html, item);
  }
  return { ...target, body_markdown: markdown, body_html: html, reviewed_media_count: media.length };
}

async function checkZhihu() {
  const response = await fetch("https://www.zhihu.com/api/v4/me", {
    credentials: "include",
    headers: { "x-requested-with": "fetch" },
  });
  if (!response.ok) return null;
  const data = await response.json();
  return data.id ? account("zhihu", data.id, data.name, data.avatar_url) : null;
}

async function writeZhihu(target) {
  assertPortableImages(target);
  const created = await responseJson(await fetch("https://zhuanlan.zhihu.com/api/articles/drafts", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", "x-requested-with": "fetch" },
    body: JSON.stringify({ title: target.title, content: "", delta_time: 0 }),
  }), "知乎草稿创建失败");
  if (!created.id) throw new Error("知乎未返回草稿编号");
  const content = String(target.body_html || "")
    .replace(/<img([^>]+)src="([^"]+)"([^>]*)>/gi, '<figure><img$1src="$2"$3></figure>')
    .replace(/\s*data-(?!draft)[a-z-]+="[^"]*"/gi, "")
    .replace(/\s*style="[^"]*"/gi, "");
  const updated = await fetch(`https://zhuanlan.zhihu.com/api/articles/${created.id}/draft`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json", "x-requested-with": "fetch" },
    body: JSON.stringify({ title: target.title, content }),
  });
  if (!updated.ok) throw new Error(`知乎草稿正文保存失败（${updated.status}）`);
  return { external_draft_id: String(created.id), draft_url: `https://zhuanlan.zhihu.com/p/${created.id}/edit` };
}

async function checkJuejin() {
  const response = await fetch("https://api.juejin.cn/user_api/v1/user/get", { credentials: "include" });
  if (!response.ok) return null;
  const data = await response.json();
  return data.data?.user_id ? account("juejin", data.data.user_id, data.data.user_name, data.data.avatar_large) : null;
}

async function juejinCsrf() {
  const response = await fetch("https://api.juejin.cn/user_api/v1/sys/token", {
    method: "HEAD",
    credentials: "include",
    headers: { "x-secsdk-csrf-request": "1", "x-secsdk-csrf-version": "1.2.10" },
  });
  const parts = (response.headers.get("x-ware-csrf-token") || "").split(",");
  if (parts.length < 2 || !parts[1]) throw new Error("掘金登录凭证已失效");
  return parts[1];
}

async function writeJuejin(target) {
  assertPortableImages(target);
  const csrf = await juejinCsrf();
  const created = await responseJson(await fetch("https://api.juejin.cn/content_api/v1/article_draft/create", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", "x-secsdk-csrf-token": csrf },
    body: JSON.stringify({
      brief_content: target.summary || "",
      category_id: "0",
      cover_image: "",
      edit_type: 10,
      html_content: "deprecated",
      link_url: "",
      mark_content: target.body_markdown || "",
      tag_ids: [],
      title: target.title,
    }),
  }), "掘金草稿创建失败");
  if (created.err_no && created.err_no !== 0) throw new Error(created.err_msg || "掘金草稿创建失败");
  const id = created.data?.id;
  if (!id) throw new Error("掘金未返回草稿编号");
  return { external_draft_id: String(id), draft_url: `https://juejin.cn/editor/drafts/${id}` };
}

async function checkCsdn() {
  // CSDN's editor API requires a platform client signature. We deliberately
  // do not copy a third-party embedded API key into this extension.
  return null;
}

async function writeCsdn(target) {
  assertPortableImages(target);
  throw new Error("CSDN 草稿接口需要官方客户端授权；GEO 文章助手不会复制第三方固定密钥");
}

async function ctoSession() {
  const response = await fetch("https://blog.51cto.com/blogger/publish", { credentials: "include" });
  const html = await response.text();
  const user = html.match(/<li class="more user">\s*<a[^>]*href="([^"]+)"[^>]*>\s*<img[^>]*src="([^"]+)"/);
  const csrf = html.match(/<meta\s+name="csrf-token"\s+content="([^"]+)"/);
  if (!response.ok || !user || !csrf) return null;
  const id = user[1].split("/").filter(Boolean).pop() || "51cto";
  return { account: account("51cto", id, id, user[2]), csrf: csrf[1] };
}

async function check51cto() {
  return (await ctoSession())?.account || null;
}

async function write51cto(target) {
  assertPortableImages(target);
  const session = await ctoSession();
  if (!session) throw new Error("请先登录 51CTO");
  const form = new URLSearchParams({
    title: target.title,
    content: target.body_markdown || target.body_html || "",
    pid: "", cate_id: "", custom_id: "0", tag: "", abstract: target.summary || "",
    banner_type: "0", blog_type: "1", copy_code: "1", is_hide: "0", top_time: "0",
    is_comment: "0", is_old: target.body_markdown ? "0" : "2", blog_id: "", did: "",
    work_id: "", class_id: "", subjectId: "", import_type: "-1", invite_code: "",
    raffle: "", orig: "", _csrf: session.csrf,
  });
  const created = await responseJson(await fetch("https://blog.51cto.com/blogger/draft", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "X-Requested-With": "XMLHttpRequest", Accept: "application/json, text/javascript, */*; q=0.01" },
    body: form.toString(),
  }), "51CTO 草稿创建失败");
  if (created.status !== 1 || !created.data?.did) throw new Error(created.msg || "51CTO 未返回草稿编号");
  const id = String(created.data.did);
  return { external_draft_id: id, draft_url: `https://blog.51cto.com/blogger/draft/${id}` };
}

async function wechatSession() {
  const response = await fetch("https://mp.weixin.qq.com/", { credentials: "include" });
  const html = await response.text();
  const token = html.match(/data:\s*\{[\s\S]*?t:\s*["']([^"']+)["']/);
  if (!response.ok || !token) return null;
  const userName = html.match(/user_name:\s*["']([^"']+)["']/)?.[1] || "wechat";
  const nickName = html.match(/nick_name:\s*["']([^"']+)["']/)?.[1] || "微信公众号";
  let avatar = html.match(/class="weui-desktop-account__thumb"[^>]*src="([^"]+)"/)?.[1] || "";
  if (avatar.startsWith("http://")) avatar = avatar.replace("http://", "https://");
  return { account: account("wechat", userName, nickName, avatar), token: token[1] };
}

async function checkWechat() {
  return (await wechatSession())?.account || null;
}

async function writeWechat(target) {
  assertPortableImages(target);
  const session = await wechatSession();
  if (!session) throw new Error("请先登录微信公众号");
  const form = new URLSearchParams({
    token: session.token, lang: "zh_CN", f: "json", ajax: "1", random: String(Math.random()),
    AppMsgId: "", count: "1", data_seq: "0", operate_from: "Chrome", isnew: "0",
    ad_video_transition0: "", can_reward0: "0", related_video0: "", is_video_recommend0: "-1",
    title0: target.title, author0: "", writerid0: "0", fileid0: "", digest0: target.summary || "",
    auto_gen_digest0: "1", content0: target.body_html || "", sourceurl0: "", need_open_comment0: "1",
    only_fans_can_comment0: "0", cdn_url0: "", cdn_235_1_url0: "", cdn_1_1_url0: "",
    cdn_url_back0: "", crop_list0: "", music_id0: "", video_id0: "", voteid0: "",
    voteismlt0: "", supervoteid0: "", cardid0: "", cardquantity0: "", cardlimit0: "",
    vid_type0: "", show_cover_pic0: "0", shortvideofileid0: "", copyright_type0: "0",
    releasefirst0: "", platform0: "", reprint_permit_type0: "", allow_reprint0: "",
    allow_reprint_modify0: "", original_article_type0: "", ori_white_list0: "", free_content0: "",
    fee0: "0", ad_id0: "", guide_words0: "", is_share_copyright0: "0", share_copyright_url0: "",
    source_article_type0: "", reprint_recommend_title0: "", reprint_recommend_content0: "",
    share_page_type0: "0", share_imageinfo0: '{"list":[]}', share_video_id0: "", dot0: "{}",
    share_voice_id0: "", insert_ad_mode0: "", categories_list0: "[]",
  });
  const created = await responseJson(await fetch(`https://mp.weixin.qq.com/cgi-bin/operate_appmsg?t=ajax-response&sub=create&type=77&token=${encodeURIComponent(session.token)}&lang=zh_CN`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  }), "微信公众号草稿创建失败");
  if (!created.appMsgId) throw new Error(created.base_resp?.err_msg || "微信公众号未返回草稿编号");
  const id = String(created.appMsgId);
  return { external_draft_id: id, draft_url: `https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=77&appmsgid=${id}&token=${encodeURIComponent(session.token)}&lang=zh_CN` };
}

async function checkBundledAccount(platformKey) {
  const { checkBundledPlatform } = await bundledAdapters();
  const auth = await checkBundledPlatform(platformKey);
  if (!auth?.isAuthenticated) return null;
  const userId = auth.userId || auth.username || "account";
  return account(platformKey, userId, auth.username || userId, auth.avatar || "");
}

async function writeBundledPlatformDraft(platformKey, target) {
  assertPortableImages(target);
  const { writeBundledDraft } = await bundledAdapters();
  const result = await writeBundledDraft(platformKey, {
    title: target.title,
    summary: target.summary || "",
    markdown: target.body_markdown || "",
    html: target.body_html || "",
    tags: Array.isArray(target.tags) ? target.tags : [],
    category: target.category || undefined,
  });
  return {
    external_draft_id: result.postId ? String(result.postId) : "",
    draft_url: result.postUrl,
  };
}

const checks = { zhihu: checkZhihu, juejin: checkJuejin, csdn: checkCsdn, "51cto": check51cto, wechat: checkWechat };
const writers = { zhihu: writeZhihu, juejin: writeJuejin, csdn: writeCsdn, "51cto": write51cto, wechat: writeWechat };
for (const platformKey of BUNDLED_PLATFORM_KEYS) {
  checks[platformKey] = () => checkBundledAccount(platformKey);
  writers[platformKey] = (target) => writeBundledPlatformDraft(platformKey, target);
}

async function getEnabledPlatforms() {
  const stored = await chrome.storage.local.get(ENABLED_PLATFORMS_STORE);
  const enabled = stored[ENABLED_PLATFORMS_STORE];
  if (!Array.isArray(enabled)) {
    await chrome.storage.local.set({ [ENABLED_PLATFORMS_STORE]: DEFAULT_ENABLED_PLATFORMS });
    return [...DEFAULT_ENABLED_PLATFORMS];
  }
  const supported = new Set(SUPPORTED_PLATFORMS);
  return [...new Set(enabled.filter((key) => supported.has(key)))];
}

async function getPlatformStatuses() {
  const enabled = new Set(await getEnabledPlatforms());
  return Promise.all(SUPPORTED_PLATFORMS.filter((platformKey) => enabled.has(platformKey)).map(async (platformKey) => {
    if (platformKey === "csdn") {
      return {
        platformKey,
        status: "requires_authorization",
        message: "需要 CSDN 官方客户端授权",
      };
    }
    try {
      const current = await checks[platformKey]();
      return current
        ? { platformKey, status: "logged_in", account: current }
        : { platformKey, status: "not_logged_in" };
    } catch {
      return {
        platformKey,
        status: "error",
        message: "平台状态检测失败，请稍后重试",
      };
    }
  }));
}

async function getAccounts() {
  const statuses = await getPlatformStatuses();
  return statuses
    .filter((item) => item.status === "logged_in" && item.account)
    .map((item) => item.account);
}

async function writeDrafts(task, accountSelections) {
  assertTask(task);
  const selections = Array.isArray(accountSelections) ? accountSelections : [];
  const selectedByPlatform = new Map();
  for (const selection of selections) {
    if (!selection?.platformKey || !selection?.accountId) continue;
    if (selectedByPlatform.has(selection.platformKey)) throw new Error("同一平台每次只能选择一个账号");
    selectedByPlatform.set(selection.platformKey, selection.accountId);
  }
  const results = [];
  for (const target of task.targets) {
    const selectedAccountId = selectedByPlatform.get(target.platform_key);
    if (!selectedAccountId) continue;
    try {
      if (target.platform_key === "csdn") throw new Error("CSDN 草稿接口需要官方客户端授权；GEO 文章助手不会复制第三方固定密钥");
      const current = await checks[target.platform_key]();
      if (!current || current.accountId !== selectedAccountId) throw new Error("已选账号登录态已失效");
      const preparedTarget = assembleReviewedMedia(target);
      const receiptKey = draftReceiptKey(task, preparedTarget, selectedAccountId);
      const previous = await getDraftReceipt(receiptKey);
      if (previous?.state === "created" && previous.result?.draft_url) {
        results.push({
          platform_key: target.platform_key,
          request_status: "draft_link_returned",
          ...previous.result,
          message: "已复用本机保存的草稿回执，没有重复创建",
        });
        continue;
      }
      if (previous?.state === "writing") {
        throw new Error("上次写入结果尚未确认。为避免重复草稿，请先检查该平台草稿箱");
      }
      await putDraftReceipt({
        key: receiptKey,
        state: "writing",
        platformKey: target.platform_key,
        updatedAt: Date.now(),
      });
      let written;
      try {
        written = preparedTarget.reviewed_media_count > 0 && IMAGE_UPLOAD_PLATFORM_KEYS.has(target.platform_key)
          ? await writeBundledPlatformDraft(target.platform_key, preparedTarget)
          : await writers[target.platform_key](preparedTarget);
      } catch (error) {
        try { await removeDraftReceipt(receiptKey); } catch { /* 保留写入中标记比重复创建更安全。 */ }
        throw error;
      }
      try {
        await putDraftReceipt({
          key: receiptKey,
          state: "created",
          platformKey: target.platform_key,
          result: written,
          updatedAt: Date.now(),
        });
      } catch {
        // 写入前的 writing 标记仍在；后续重试会停止并要求人工检查草稿箱。
      }
      results.push({ platform_key: target.platform_key, request_status: "draft_link_returned", ...written });
    } catch (error) {
      results.push({ platform_key: target.platform_key, request_status: "failed", message: error instanceof Error ? error.message : "草稿写入失败" });
    }
  }
  if (!results.length) throw new Error("没有选择可写入的平台账号");
  return results;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.protocolVersion !== PROTOCOL) return false;
  (async () => {
    if (message.method === "health") return {
      protocolVersion: PROTOCOL,
      extensionVersion: chrome.runtime.getManifest().version,
      draftOnly: true,
      draftReceiptVersion: 1,
      supportedPlatforms: SUPPORTED_PLATFORMS,
      enabledPlatforms: await getEnabledPlatforms(),
      readyPlatforms: SUPPORTED_PLATFORMS.filter((key) => key !== "csdn"),
      unavailable: { csdn: "requires_official_authorization" },
    };
    if (message.method === "getAccounts") return getAccounts();
    if (message.method === "getPlatformStatuses") return getPlatformStatuses();
    if (message.method === "writeDrafts") return writeDrafts(message.payload?.task, message.payload?.accountSelections);
    throw new Error("不受支持的 GEO 文章助手操作");
  })().then((data) => sendResponse({ ok: true, data })).catch((error) => sendResponse({ ok: false, error: error instanceof Error ? error.message : "GEO 文章助手调用失败" }));
  return true;
});
