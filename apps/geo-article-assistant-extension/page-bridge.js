(() => {
  const PROTOCOL = "geo-article-assistant.v1";
  const REQUEST_TYPE = "GEO_ARTICLE_ASSISTANT_REQUEST";
  const RESPONSE_TYPE = "GEO_ARTICLE_ASSISTANT_RESPONSE";
  const pending = new Map();

  function request(method, payload = {}, timeoutMs = 180000) {
    return new Promise((resolve, reject) => {
      const requestId = crypto.randomUUID();
      const timeout = window.setTimeout(() => {
        pending.delete(requestId);
        reject(new Error("GEO 文章助手响应超时"));
      }, timeoutMs);
      pending.set(requestId, { resolve, reject, timeout });
      window.postMessage({ type: REQUEST_TYPE, protocolVersion: PROTOCOL, requestId, method, payload }, window.location.origin);
    });
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.origin !== window.location.origin) return;
    const message = event.data;
    if (!message || message.type !== RESPONSE_TYPE || message.protocolVersion !== PROTOCOL) return;
    const item = pending.get(message.requestId);
    if (!item) return;
    pending.delete(message.requestId);
    window.clearTimeout(item.timeout);
    if (message.response?.ok) item.resolve(message.response.data);
    else item.reject(new Error(message.response?.error || "GEO 文章助手调用失败"));
  });

  Object.defineProperty(window, "$geoArticleAssistant", {
    configurable: false,
    enumerable: false,
    writable: false,
    value: Object.freeze({
      protocolVersion: PROTOCOL,
      health: () => request("health"),
      getAccounts: () => request("getAccounts"),
      writeDrafts: (task, accountSelections) => request("writeDrafts", { task, accountSelections }),
    }),
  });
})();
