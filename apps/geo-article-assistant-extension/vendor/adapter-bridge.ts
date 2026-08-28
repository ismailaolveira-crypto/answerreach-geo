import type { Article, AuthResult, HeaderRule, SyncResult } from "./wechatsync-core/src/types";
import type { RuntimeInterface } from "./wechatsync-core/src/runtime/interface";
import { BaijiahaoAdapter } from "./wechatsync-core/src/adapters/platforms/baijiahao";
import { BilibiliAdapter } from "./wechatsync-core/src/adapters/platforms/bilibili";
import { CnblogsAdapter } from "./wechatsync-core/src/adapters/platforms/cnblogs";
import { DoubanAdapter } from "./wechatsync-core/src/adapters/platforms/douban";
import { EastmoneyAdapter } from "./wechatsync-core/src/adapters/platforms/eastmoney";
import { ImoocAdapter } from "./wechatsync-core/src/adapters/platforms/imooc";
import { OschinaAdapter } from "./wechatsync-core/src/adapters/platforms/oschina";
import { SegmentfaultAdapter } from "./wechatsync-core/src/adapters/platforms/segmentfault";
import { SohuAdapter } from "./wechatsync-core/src/adapters/platforms/sohu";
import { WeiboAdapter } from "./wechatsync-core/src/adapters/platforms/weibo";
import { WoshipmAdapter } from "./wechatsync-core/src/adapters/platforms/woshipm";
import { XueqiuAdapter } from "./wechatsync-core/src/adapters/platforms/xueqiu";
import { YuqueAdapter } from "./wechatsync-core/src/adapters/platforms/yuque";
import { ZhihuAdapter } from "./wechatsync-core/src/adapters/platforms/zhihu";
import { JuejinAdapter } from "./wechatsync-core/src/adapters/platforms/juejin";
import { Cto51Adapter } from "./wechatsync-core/src/adapters/platforms/cto51";
import { WeixinAdapter } from "./wechatsync-core/src/adapters/platforms/weixin";

type Adapter = {
  init(runtime: RuntimeInterface): Promise<void>;
  checkAuth(): Promise<AuthResult>;
  publish(article: Article, options?: { draftOnly?: boolean }): Promise<SyncResult>;
};

type AdapterConstructor = new () => Adapter;

const ADAPTERS: Record<string, AdapterConstructor> = {
	zhihu: ZhihuAdapter,
	juejin: JuejinAdapter,
	"51cto": Cto51Adapter,
	wechat: WeixinAdapter,
  baijiahao: BaijiahaoAdapter,
  bilibili: BilibiliAdapter,
  cnblogs: CnblogsAdapter,
  douban: DoubanAdapter,
  eastmoney: EastmoneyAdapter,
  imooc: ImoocAdapter,
  oschina: OschinaAdapter,
  segmentfault: SegmentfaultAdapter,
  sohu: SohuAdapter,
  weibo: WeiboAdapter,
  woshipm: WoshipmAdapter,
  xueqiu: XueqiuAdapter,
  yuque: YuqueAdapter,
};

let dynamicRuleId = 10_000;

const runtime: RuntimeInterface = {
  type: "extension",
  async fetch(url, options = {}) {
    return fetch(url, { ...options, credentials: "include" });
  },
  cookies: {
    async get(domain) {
      return (await chrome.cookies.getAll({ domain })).map((cookie) => ({
        name: cookie.name,
        value: cookie.value,
        domain: cookie.domain,
        path: cookie.path,
        secure: cookie.secure,
        httpOnly: cookie.httpOnly,
        expirationDate: cookie.expirationDate,
      }));
    },
    async set(cookie) {
      await chrome.cookies.set({
        url: `https://${cookie.domain}${cookie.path || "/"}`,
        name: cookie.name,
        value: cookie.value,
        domain: cookie.domain,
        path: cookie.path,
        secure: cookie.secure,
        httpOnly: cookie.httpOnly,
        expirationDate: cookie.expirationDate,
      });
    },
    async remove(name, domain) {
      await chrome.cookies.remove({ url: `https://${domain}`, name });
    },
  },
  async getCookie(domain, name) {
    const rows = await chrome.cookies.getAll({ domain, name });
    return rows[0]?.value || null;
  },
  storage: {
    async get(key) { return (await chrome.storage.local.get(key))[key] ?? null; },
    async set(key, value) { await chrome.storage.local.set({ [key]: value }); },
    async remove(key) { await chrome.storage.local.remove(key); },
  },
  session: {
    async get(key) { return (await chrome.storage.session.get(key))[key] ?? null; },
    async set(key, value) { await chrome.storage.session.set({ [key]: value }); },
  },
  headerRules: {
    async add(rule: HeaderRule) {
      const id = dynamicRuleId++;
      await chrome.declarativeNetRequest.updateDynamicRules({
        addRules: [{
          id,
          priority: 1,
          action: {
            type: "modifyHeaders",
            requestHeaders: Object.entries(rule.headers).map(([header, value]) => ({ header, operation: "set", value })),
          },
          condition: {
            urlFilter: rule.urlFilter,
            initiatorDomains: [chrome.runtime.id],
            resourceTypes: rule.resourceTypes || ["xmlhttprequest"],
          },
        }],
      });
      return `rule_${id}`;
    },
    async remove(ruleId) {
      await chrome.declarativeNetRequest.updateDynamicRules({ removeRuleIds: [Number(ruleId.replace("rule_", ""))] });
    },
    async clear() {
      const rules = await chrome.declarativeNetRequest.getDynamicRules();
      await chrome.declarativeNetRequest.updateDynamicRules({ removeRuleIds: rules.map((rule) => rule.id) });
    },
  },
  dom: {
    async parseHTML() { throw new Error("DOM parsing is not available in the background worker"); },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    getTextContent(element) { return element.textContent || ""; },
    getInnerHTML(element) { return element.innerHTML; },
  },
};

const instances = new Map<string, Adapter>();

async function adapterFor(platformKey: string) {
  const existing = instances.get(platformKey);
  if (existing) return existing;
  const AdapterClass = ADAPTERS[platformKey];
  if (!AdapterClass) throw new Error("未找到平台适配器");
  const adapter = new AdapterClass();
  await adapter.init(runtime);
  instances.set(platformKey, adapter);
  return adapter;
}

export async function checkBundledPlatform(platformKey: string) {
  return (await adapterFor(platformKey)).checkAuth();
}

export async function writeBundledDraft(platformKey: string, article: Article) {
  const result = await (await adapterFor(platformKey)).publish(article, { draftOnly: true });
  if (!result.success) throw new Error(result.error || result.message || "平台草稿写入失败");
  if (result.draftOnly === false) throw new Error("平台未确认草稿模式，已停止后续操作");
  if (!result.postUrl) throw new Error("平台未返回可回读的草稿链接");
  return result;
}
