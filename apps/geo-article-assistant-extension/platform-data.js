export const ENABLED_PLATFORMS_STORE = "geoArticleAssistantEnabledPlatformsV1";

export const DEFAULT_ENABLED_PLATFORMS = ["wechat", "zhihu", "juejin", "51cto", "csdn"];

export const PLATFORMS = [
  { key: "wechat", label: "微信公众号", category: "内容 · 自媒体", logo: "assets/platforms/wechat.svg", origins: ["https://mp.weixin.qq.com/*"] },
  { key: "zhihu", label: "知乎", category: "问答 · 社区", logo: "assets/platforms/zhihu.svg", origins: ["https://www.zhihu.com/*", "https://zhuanlan.zhihu.com/*"] },
  { key: "juejin", label: "掘金", category: "技术 · 社区", logo: "assets/platforms/juejin.png", origins: ["https://api.juejin.cn/*", "https://juejin.cn/*"] },
  { key: "51cto", label: "51CTO", category: "技术 · 社区", logo: "assets/platforms/51cto.png", origins: ["https://blog.51cto.com/*", "https://home.51cto.com/*"] },
  { key: "csdn", label: "CSDN", category: "技术 · 社区", logo: "assets/platforms/csdn.ico", origins: [], authorizationOnly: true },
  { key: "bilibili", label: "哔哩哔哩", category: "视频 · 社区", logo: "assets/platforms/bilibili.ico", origins: ["https://api.bilibili.com/*", "https://member.bilibili.com/*"], needsCookies: true },
  { key: "baijiahao", label: "百家号", category: "内容 · 自媒体", logo: "assets/platforms/baijiahao.ico", origins: ["https://baijiahao.baidu.com/*"] },
  { key: "weibo", label: "微博", category: "社交 · 自媒体", logo: "assets/platforms/weibo.ico", origins: ["https://weibo.com/*", "https://card.weibo.com/*", "https://picupload.weibo.com/*"] },
  { key: "yuque", label: "语雀", category: "文档 · 知识库", logo: "assets/platforms/yuque.png", origins: ["https://www.yuque.com/*"], needsCookies: true },
  { key: "douban", label: "豆瓣", category: "社区 · 书影音", logo: "assets/platforms/douban.ico", origins: ["https://www.douban.com/*"] },
  { key: "sohu", label: "搜狐号", category: "内容 · 自媒体", logo: "assets/platforms/sohu.ico", origins: ["https://mp.sohu.com/*"], needsCookies: true },
  { key: "xueqiu", label: "雪球", category: "投资 · 社区", logo: "assets/platforms/xueqiu.ico", origins: ["https://mp.xueqiu.com/*"] },
  { key: "cnblogs", label: "博客园", category: "技术 · 博客", logo: "assets/platforms/cnblogs.ico", origins: ["https://www.cnblogs.com/*", "https://i.cnblogs.com/*", "https://home.cnblogs.com/*", "https://upload.cnblogs.com/*"], needsCookies: true },
  { key: "oschina", label: "开源中国", category: "开源 · 社区", logo: "assets/platforms/oschina.ico", origins: ["https://www.oschina.net/*", "https://my.oschina.net/*", "https://apiv1.oschina.net/*"] },
  { key: "segmentfault", label: "思否", category: "技术 · 问答", logo: "assets/platforms/segmentfault.png", origins: ["https://segmentfault.com/*"] },
  { key: "imooc", label: "慕课手记", category: "学习 · 笔记", logo: "assets/platforms/imooc.ico", origins: ["https://www.imooc.com/*"] },
  { key: "woshipm", label: "人人都是产品经理", category: "产品 · 社区", logo: "assets/platforms/woshipm.ico", origins: ["https://www.woshipm.com/*"] },
  { key: "eastmoney", label: "东方财富", category: "财经 · 社区", logo: "assets/platforms/eastmoney.ico", origins: ["https://mp.eastmoney.com/*", "https://caifuhaoapi.eastmoney.com/*", "https://emfront.eastmoney.com/*", "https://gbapi.eastmoney.com/*"], needsCookies: true },
];

export async function readEnabledPlatformKeys() {
  const stored = await chrome.storage.local.get(ENABLED_PLATFORMS_STORE);
  const enabled = stored[ENABLED_PLATFORMS_STORE];
  if (!Array.isArray(enabled)) {
    await chrome.storage.local.set({ [ENABLED_PLATFORMS_STORE]: DEFAULT_ENABLED_PLATFORMS });
    return [...DEFAULT_ENABLED_PLATFORMS];
  }
  const allowed = new Set(PLATFORMS.map((platform) => platform.key));
  return [...new Set(enabled.filter((key) => allowed.has(key)))];
}

export async function writeEnabledPlatformKeys(keys) {
  const allowed = new Set(PLATFORMS.map((platform) => platform.key));
  const next = [...new Set(keys.filter((key) => allowed.has(key)))];
  await chrome.storage.local.set({ [ENABLED_PLATFORMS_STORE]: next });
  return next;
}
