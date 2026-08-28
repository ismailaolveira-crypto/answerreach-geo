const PROTOCOL = "geo-article-assistant.v1";
const REQUEST_TYPE = "GEO_ARTICLE_ASSISTANT_REQUEST";
const RESPONSE_TYPE = "GEO_ARTICLE_ASSISTANT_RESPONSE";
const allowedOrigins = new Set(["http://localhost:39003", "http://127.0.0.1:39003"]);

const bridge = document.createElement("script");
bridge.src = chrome.runtime.getURL("page-bridge.js");
bridge.async = false;
bridge.onload = () => bridge.remove();
(document.head || document.documentElement).appendChild(bridge);

window.addEventListener("message", async (event) => {
  if (event.source !== window || !allowedOrigins.has(event.origin)) return;
  const request = event.data;
  if (!request || request.type !== REQUEST_TYPE || request.protocolVersion !== PROTOCOL) return;
  const requestId = typeof request.requestId === "string" ? request.requestId : "";
  if (!requestId) return;
  try {
    const response = await chrome.runtime.sendMessage({
      protocolVersion: PROTOCOL,
      method: request.method,
      payload: request.payload || {},
    });
    window.postMessage({ type: RESPONSE_TYPE, protocolVersion: PROTOCOL, requestId, response }, event.origin);
  } catch (error) {
    window.postMessage({
      type: RESPONSE_TYPE,
      protocolVersion: PROTOCOL,
      requestId,
      response: { ok: false, error: error instanceof Error ? error.message : "GEO 文章助手调用失败" },
    }, event.origin);
  }
});
