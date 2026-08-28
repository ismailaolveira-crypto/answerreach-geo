import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const source = await readFile(new URL("../background.js", import.meta.url), "utf8");
for (const file of ["../background.js", "../content-script.js", "../page-bridge.js"]) {
  new vm.Script(await readFile(new URL(file, import.meta.url), "utf8"), { filename: file });
}
let messageListener;
const fetchCalls = [];
const extensionStorage = {};

function json(data, init = {}) {
  return new Response(JSON.stringify(data), {
    status: init.status ?? 200,
    headers: { "content-type": "application/json", ...(init.headers || {}) },
  });
}

async function fakeFetch(input, init = {}) {
  const url = String(input);
  fetchCalls.push({ url, method: init.method || "GET", body: String(init.body || "") });
  if (url === "https://www.zhihu.com/api/v4/me") return json({ id: "zh-user", name: "知乎测试号", avatar_url: "https://img.example/zh.png" });
  if (url === "https://zhuanlan.zhihu.com/api/articles/drafts") return json({ id: 101 });
  if (url === "https://zhuanlan.zhihu.com/api/articles/101/draft" && init.method === "PATCH") return json({ ok: true });
  if (url === "https://api.juejin.cn/user_api/v1/user/get") return json({ data: { user_id: "jj-user", user_name: "掘金测试号", avatar_large: "https://img.example/jj.png" } });
  if (url === "https://api.juejin.cn/user_api/v1/sys/token") return new Response("", { status: 200, headers: { "x-ware-csrf-token": "0,juejin-csrf" } });
  if (url === "https://api.juejin.cn/content_api/v1/article_draft/create") return json({ err_no: 0, data: { id: 202 } });
  if (url === "https://blog.51cto.com/blogger/publish") return new Response('<meta name="csrf-token" content="cto-csrf"><li class="more user"><a href="https://blog.51cto.com/cto-user"><img src="https://img.example/cto.png">', { status: 200 });
  if (url === "https://blog.51cto.com/blogger/draft") return json({ status: 1, data: { did: 303 } });
  if (url === "https://mp.weixin.qq.com/") return new Response('data: { t: "wx-token" } user_name: "wx-user" nick_name: "公众号测试号" class="weui-desktop-account__thumb" src="https://img.example/wx.png"', { status: 200 });
  if (url.startsWith("https://mp.weixin.qq.com/cgi-bin/operate_appmsg?")) return json({ appMsgId: 404 });
  throw new Error(`Unexpected fetch: ${url}`);
}

const chrome = {
  runtime: {
    getManifest: () => ({ version: "0.3.0" }),
    onMessage: { addListener: (listener) => { messageListener = listener; } },
  },
  storage: {
    local: {
      async get(key) { return { [key]: extensionStorage[key] }; },
      async set(values) { Object.assign(extensionStorage, values); },
    },
  },
};

const backgroundContext = {
  chrome,
  console,
  Date,
  encodeURIComponent,
  Error,
  fetch: fakeFetch,
  Map,
  Math,
  Promise,
  Response,
  Set,
  URLSearchParams,
};
vm.runInNewContext(source, backgroundContext, { filename: "background.js" });

assert.equal(typeof messageListener, "function");
assert.equal(typeof backgroundContext.assembleReviewedMedia, "function");

const preparedMediaTarget = backgroundContext.assembleReviewedMedia({
  body_markdown: "第一段\n\n第二段",
  body_html: "<p>第一段</p><p>第二段</p>",
  image_manifest: [
    {
      artifact_id: 9,
      review_status: "approved",
      quality_gate: "passed",
      content_url: "http://localhost:39003/api/geo/1/distribution-runs/7/assistant-media/9?task_token=abcdefghijklmnopqrstuvwxyz_123456",
      alt_text: "GEO 流程图",
      caption: "从内容到复测的闭环",
      placement: "after_intro",
    },
    {
      artifact_id: 10,
      review_status: "pending",
      quality_gate: "passed",
      content_url: "http://localhost:39003/api/geo/1/distribution-runs/7/assistant-media/10?task_token=abcdefghijklmnopqrstuvwxyz_123456",
      alt_text: "不应插入",
    },
  ],
});
assert.equal(preparedMediaTarget.reviewed_media_count, 1);
assert.match(preparedMediaTarget.body_markdown, /!\[GEO 流程图\]\(http:\/\/localhost:39003\/api\/geo\/1\/distribution-runs\/7\/assistant-media\/9\?task_token=/);
assert.match(preparedMediaTarget.body_markdown, /\*图注：从内容到复测的闭环\*/);
assert.match(preparedMediaTarget.body_html, /<figcaption>图注：从内容到复测的闭环<\/figcaption>/);
assert.doesNotMatch(preparedMediaTarget.body_html, /assistant-media\/10/);

function send(method, payload = {}) {
  return new Promise((resolve) => {
    const keepAlive = messageListener({ protocolVersion: "geo-article-assistant.v1", method, payload }, {}, resolve);
    assert.equal(keepAlive, true);
  });
}

const health = await send("health");
const expectedPlatformKeys = [
  "wechat", "zhihu", "juejin", "51cto", "csdn", "bilibili", "baijiahao", "weibo", "yuque",
  "douban", "sohu", "xueqiu", "cnblogs", "oschina", "segmentfault", "imooc", "woshipm", "eastmoney",
];
assert.equal(health.ok, true);
assert.equal(health.data.draftOnly, true);
assert.equal(health.data.draftReceiptVersion, 1);
assert.deepEqual([...health.data.supportedPlatforms], expectedPlatformKeys);
assert.deepEqual([...health.data.enabledPlatforms], ["wechat", "zhihu", "juejin", "51cto", "csdn"]);
assert.equal(health.data.readyPlatforms.length, 17);
assert.equal(health.data.unavailable.csdn, "requires_official_authorization");

const accounts = await send("getAccounts");
assert.equal(accounts.ok, true);
assert.deepEqual([...accounts.data.map((item) => item.platformKey)], ["wechat", "zhihu", "juejin", "51cto"]);

const statuses = await send("getPlatformStatuses");
assert.equal(statuses.ok, true);
assert.deepEqual([...statuses.data.map((item) => item.platformKey)], ["wechat", "zhihu", "juejin", "51cto", "csdn"]);
assert.equal(statuses.data.find((item) => item.platformKey === "csdn").status, "requires_authorization");
assert.ok(statuses.data.filter((item) => item.status === "logged_in").length === 4);

const task = {
  protocol_version: "geo-article-assistant.v1",
  task_token: "one-time-token",
  run_id: 77,
  content_fingerprint: "content-fingerprint",
  expires_at: new Date(Date.now() + 60_000).toISOString(),
  targets: ["zhihu", "juejin", "51cto", "wechat"].map((platform_key) => ({
    platform_key,
    content_fingerprint: `${platform_key}-content-fingerprint`,
    title: `${platform_key} 测试标题`,
    summary: "测试摘要",
    body_markdown: "## 已审核正文\n\n[查看证据](https://example.com/evidence)\n\n![远程配图](https://img.example/approved.png)\n\n```js\nconst approved = true;\n```",
    body_html: '<h2>已审核正文</h2><p><a href="https://example.com/evidence">查看证据</a></p><img src="https://img.example/approved.png"><pre><code>const approved = true;</code></pre>',
  })),
};
const selections = accounts.data.map((item) => ({ platformKey: item.platformKey, accountId: item.accountId }));
const written = await send("writeDrafts", { task, accountSelections: selections });
assert.equal(written.ok, true);
assert.equal(written.data.length, 4);
assert.ok(written.data.every((item) => item.request_status === "draft_link_returned" && item.draft_url.startsWith("https://")));

const createRequestCount = () => fetchCalls.filter((call) =>
  call.url === "https://zhuanlan.zhihu.com/api/articles/drafts"
  || call.url === "https://api.juejin.cn/content_api/v1/article_draft/create"
  || call.url === "https://blog.51cto.com/blogger/draft"
  || call.url.startsWith("https://mp.weixin.qq.com/cgi-bin/operate_appmsg?")
).length;
const firstCreateRequestCount = createRequestCount();
const replayedWrite = await send("writeDrafts", { task, accountSelections: selections });
assert.equal(replayedWrite.ok, true);
assert.equal(replayedWrite.data.length, 4);
assert.ok(replayedWrite.data.every((item) => item.request_status === "draft_link_returned"));
assert.ok(replayedWrite.data.every((item) => /没有重复创建/.test(item.message)));
assert.equal(createRequestCount(), firstCreateRequestCount);

const manifest = JSON.parse(await readFile(new URL("../manifest.json", import.meta.url), "utf8"));
assert.equal(manifest.version, "0.3.0");
assert.ok(manifest.permissions.includes("storage"));
assert.ok(manifest.optional_permissions.includes("cookies"));
assert.ok(manifest.optional_host_permissions.includes("https://api.bilibili.com/*"));
assert.equal(manifest.options_page, "platforms.html");
assert.equal(manifest.action.default_popup, "popup.html");
assert.equal(manifest.action.default_icon[32], "assets/icons/icon-32.png");
assert.ok(manifest.host_permissions.includes("https://home.51cto.com/*"));
assert.ok(!manifest.host_permissions.includes("https://bizapi.csdn.net/*"));
assert.ok(!manifest.host_permissions.includes("https://editor.csdn.net/*"));
assert.ok(manifest.host_permissions.includes("https://api.zhihu.com/*"));
assert.ok(manifest.host_permissions.includes("https://zhihu-pics-upload.zhimg.com/*"));
assert.ok(manifest.host_permissions.includes("https://*.bytedanceapi.com/*"));
const bundledSource = await readFile(new URL("../vendor/wechatsync-adapters.js", import.meta.url), "utf8");
assert.match(bundledSource, /zhihu:\s*ZhihuAdapter/);
assert.match(bundledSource, /juejin:\s*JuejinAdapter/);
assert.match(bundledSource, /"51cto":\s*Cto51Adapter/);
assert.match(bundledSource, /wechat:\s*WeixinAdapter/);

const platformDataUrl = new URL("../platform-data.js", import.meta.url);
const platformDataSource = await readFile(platformDataUrl, "utf8");
const platformData = await import(platformDataUrl);
assert.deepEqual(platformData.PLATFORMS.map((platform) => platform.key), expectedPlatformKeys);
const declaredOrigins = new Set([...manifest.host_permissions, ...manifest.optional_host_permissions]);
for (const platform of platformData.PLATFORMS) {
  for (const origin of platform.origins) assert.ok(declaredOrigins.has(origin), `${platform.key} missing ${origin}`);
}
assert.deepEqual(platformData.PLATFORMS.find((platform) => platform.key === "csdn").origins, []);
assert.match(platformDataSource, /geoArticleAssistantEnabledPlatformsV1/);
const platformsHtml = await readFile(new URL("../platforms.html", import.meta.url), "utf8");
assert.match(platformsHtml, /平台目录/);
assert.match(platformsHtml, /只写草稿，不自动发布/);
assert.match(platformsHtml, /catalogPagination/);
assert.match(platformsHtml, /previousPageButton/);
const platformsSource = await readFile(new URL("../platforms.js", import.meta.url), "utf8");
assert.match(platformsSource, /const PAGE_SIZE = 8/);
assert.match(platformsSource, /第 \$\{currentPage\} \/ \$\{totalPages\} 页/);

const zhihuPatch = fetchCalls.find((call) => call.url.endsWith("/api/articles/101/draft") && call.method === "PATCH");
assert.ok(zhihuPatch);
const zhihuBody = JSON.parse(zhihuPatch.body);
assert.match(zhihuBody.content, /<a href="https:\/\/example\.com\/evidence">/);
assert.match(zhihuBody.content, /<figure><img src="https:\/\/img\.example\/approved\.png"><\/figure>/);
assert.match(zhihuBody.content, /<pre><code>const approved = true;<\/code><\/pre>/);

const juejinCreate = fetchCalls.find((call) => call.url.endsWith("/content_api/v1/article_draft/create"));
assert.ok(juejinCreate);
const juejinBody = JSON.parse(juejinCreate.body);
assert.match(juejinBody.mark_content, /\[查看证据\]\(https:\/\/example\.com\/evidence\)/);
assert.match(juejinBody.mark_content, /!\[远程配图\]\(https:\/\/img\.example\/approved\.png\)/);
assert.match(juejinBody.mark_content, /```js\nconst approved = true;\n```/);

const ctoCreate = fetchCalls.find((call) => call.url === "https://blog.51cto.com/blogger/draft");
assert.ok(ctoCreate);
const ctoBody = new URLSearchParams(ctoCreate.body).get("content");
assert.match(ctoBody, /\[查看证据\]\(https:\/\/example\.com\/evidence\)/);
assert.match(ctoBody, /!\[远程配图\]\(https:\/\/img\.example\/approved\.png\)/);
assert.match(ctoBody, /```js\nconst approved = true;\n```/);

const wechatCreate = fetchCalls.find((call) => call.url.startsWith("https://mp.weixin.qq.com/cgi-bin/operate_appmsg?"));
assert.ok(wechatCreate);
const wechatBody = new URLSearchParams(wechatCreate.body).get("content0");
assert.match(wechatBody, /<a href="https:\/\/example\.com\/evidence">/);
assert.match(wechatBody, /<img src="https:\/\/img\.example\/approved\.png">/);
assert.match(wechatBody, /<pre><code>const approved = true;<\/code><\/pre>/);

const csdnTask = { ...task, targets: [{ ...task.targets[0], platform_key: "csdn" }] };
const csdn = await send("writeDrafts", { task: csdnTask, accountSelections: [{ platformKey: "csdn", accountId: "csdn:test" }] });
assert.equal(csdn.ok, true);
assert.equal(csdn.data[0].request_status, "failed");
assert.match(csdn.data[0].message, /官方客户端授权/);

const expired = await send("writeDrafts", { task: { ...task, expires_at: new Date(Date.now() - 1000).toISOString() }, accountSelections: selections });
assert.equal(expired.ok, false);
assert.match(expired.error, /已过期/);

const unsafeImageTask = { ...task, targets: [{ ...task.targets[0], body_html: '<img src="file:///tmp/private.png">' }] };
const zhihuSelection = selections.find((item) => item.platformKey === "zhihu");
const unsafeImage = await send("writeDrafts", { task: unsafeImageTask, accountSelections: [zhihuSelection] });
assert.equal(unsafeImage.ok, true);
assert.equal(unsafeImage.data[0].request_status, "failed");
assert.match(unsafeImage.data[0].message, /本地或非 HTTPS 图片/);

const contentSource = await readFile(new URL("../content-script.js", import.meta.url), "utf8");
const contentListeners = new Map();
const contentPosts = [];
let extensionMessageCount = 0;
const contentWindow = {
  addEventListener(type, listener) { contentListeners.set(type, listener); },
  postMessage(message, origin) { contentPosts.push({ message, origin }); },
};
const bridgeElement = { async: true, onload: null, remove() {} };
const contentDocument = {
  createElement() { return bridgeElement; },
  head: { appendChild(element) { element.onload?.(); } },
  documentElement: { appendChild(element) { element.onload?.(); } },
};
const contentChrome = {
  runtime: {
    getURL: (path) => `chrome-extension://geo-assistant/${path}`,
    async sendMessage() { extensionMessageCount += 1; return { ok: true, data: { draftOnly: true } }; },
  },
};
vm.runInNewContext(contentSource, { chrome: contentChrome, document: contentDocument, Error, Set, window: contentWindow });
const contentHandler = contentListeners.get("message");
assert.equal(typeof contentHandler, "function");
await contentHandler({ source: contentWindow, origin: "https://attacker.example", data: { type: "GEO_ARTICLE_ASSISTANT_REQUEST", protocolVersion: "geo-article-assistant.v1", requestId: "bad", method: "health" } });
assert.equal(extensionMessageCount, 0);
await contentHandler({ source: contentWindow, origin: "http://localhost:39003", data: { type: "GEO_ARTICLE_ASSISTANT_REQUEST", protocolVersion: "geo-article-assistant.v1", requestId: "good", method: "health" } });
assert.equal(extensionMessageCount, 1);
assert.equal(contentPosts.at(-1).origin, "http://localhost:39003");
assert.equal(contentPosts.at(-1).message.response.data.draftOnly, true);

const pageSource = await readFile(new URL("../page-bridge.js", import.meta.url), "utf8");
const pageListeners = new Map();
const pagePosts = [];
const pageWindow = {
  location: { origin: "http://localhost:39003" },
  addEventListener(type, listener) { pageListeners.set(type, listener); },
  postMessage(message, origin) { pagePosts.push({ message, origin }); },
  setTimeout() { return 1; },
  clearTimeout() {},
};
vm.runInNewContext(pageSource, { crypto: { randomUUID: () => "request-1" }, Error, Map, Object, Promise, window: pageWindow });
assert.deepEqual(Object.keys(pageWindow.$geoArticleAssistant).sort(), ["getAccounts", "health", "protocolVersion", "writeDrafts"]);
assert.equal(Object.isFrozen(pageWindow.$geoArticleAssistant), true);
assert.equal("publish" in pageWindow.$geoArticleAssistant, false);
const pageHealthPromise = pageWindow.$geoArticleAssistant.health();
assert.equal(pagePosts[0].origin, "http://localhost:39003");
assert.equal(pagePosts[0].message.method, "health");
pageListeners.get("message")({ source: pageWindow, origin: "https://attacker.example", data: { type: "GEO_ARTICLE_ASSISTANT_RESPONSE", protocolVersion: "geo-article-assistant.v1", requestId: "request-1", response: { ok: true, data: { draftOnly: false } } } });
pageListeners.get("message")({ source: pageWindow, origin: "http://localhost:39003", data: { type: "GEO_ARTICLE_ASSISTANT_RESPONSE", protocolVersion: "geo-article-assistant.v1", requestId: "request-1", response: { ok: true, data: { draftOnly: true } } } });
assert.deepEqual(await pageHealthPromise, { draftOnly: true });

console.log("geo-article-assistant smoke: ok");
