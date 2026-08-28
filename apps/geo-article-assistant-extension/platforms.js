import { PLATFORMS, readEnabledPlatformKeys, writeEnabledPlatformKeys } from "./platform-data.js";

const GEO_URL = "http://localhost:39003/geo/1/settings#agent";
const catalogGrid = document.querySelector("#catalogGrid");
const searchInput = document.querySelector("#searchInput");
const emptyState = document.querySelector("#emptyState");
const enabledCount = document.querySelector("#enabledCount");
const filterEnabledCount = document.querySelector("#filterEnabledCount");
const filterDisabledCount = document.querySelector("#filterDisabledCount");
const totalCount = document.querySelector("#totalCount");
const allCount = document.querySelector("#allCount");
const catalogPagination = document.querySelector("#catalogPagination");
const previousPageButton = document.querySelector("#previousPageButton");
const nextPageButton = document.querySelector("#nextPageButton");
const pageIndicators = document.querySelector("#pageIndicators");
const pageSummary = document.querySelector("#pageSummary");

const PAGE_SIZE = 8;
let enabledKeys = [];
let activeFilter = "all";
let currentPage = 1;

function updateCounts() {
  enabledCount.textContent = String(enabledKeys.length);
  filterEnabledCount.textContent = String(enabledKeys.length);
  filterDisabledCount.textContent = String(PLATFORMS.length - enabledKeys.length);
  totalCount.textContent = String(PLATFORMS.length);
  allCount.textContent = String(PLATFORMS.length);
}

function permissionPayload(platform) {
  return {
    origins: platform.origins,
    ...(platform.needsCookies ? { permissions: ["cookies"] } : {}),
  };
}

async function addPlatform(platform, button) {
  button.dataset.loading = "true";
  button.disabled = true;
  try {
    const granted = platform.origins.length
      ? await chrome.permissions.request(permissionPayload(platform))
      : true;
    if (!granted) return;
    enabledKeys = await writeEnabledPlatformKeys([...enabledKeys, platform.key]);
    render();
  } finally {
    button.dataset.loading = "false";
    button.disabled = false;
  }
}

async function removePlatform(platform, button) {
  button.dataset.loading = "true";
  button.disabled = true;
  try {
    const next = enabledKeys.filter((key) => key !== platform.key);
    enabledKeys = await writeEnabledPlatformKeys(next);
    const otherCookiePlatform = PLATFORMS.some((item) => item.needsCookies && next.includes(item.key));
    await chrome.permissions.remove({
      origins: platform.origins,
      ...(platform.needsCookies && !otherCookiePlatform ? { permissions: ["cookies"] } : {}),
    });
    render();
  } finally {
    button.dataset.loading = "false";
    button.disabled = false;
  }
}

function createCard(platform) {
  const enabled = enabledKeys.includes(platform.key);
  const card = document.createElement("article");
  card.className = "platform-card";

  const logo = document.createElement("img");
  logo.src = platform.logo;
  logo.alt = `${platform.label} 官方标志`;

  const copy = document.createElement("div");
  copy.className = "card-copy";
  const title = document.createElement("h2");
  title.textContent = platform.label;
  const category = document.createElement("p");
  category.textContent = platform.category;
  const button = document.createElement("button");
  button.type = "button";
  button.className = `platform-toggle${enabled ? " enabled" : ""}${platform.authorizationOnly ? " authorization" : ""}`;
  button.textContent = enabled
    ? platform.authorizationOnly ? "✓ 已添加 · 需官方授权" : "✓ 已添加"
    : "+ 添加";
  button.setAttribute("aria-pressed", String(enabled));
  button.addEventListener("click", () => enabled ? removePlatform(platform, button) : addPlatform(platform, button));
  copy.append(title, category, button);
  card.append(logo, copy);
  return card;
}

function renderPagination(totalItems, totalPages) {
  catalogPagination.hidden = totalItems === 0;
  previousPageButton.disabled = currentPage === 1;
  nextPageButton.disabled = currentPage === totalPages;
  pageSummary.textContent = `第 ${currentPage} / ${totalPages} 页`;
  pageIndicators.replaceChildren(...Array.from({ length: totalPages }, (_, index) => {
    const page = index + 1;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `page-number${page === currentPage ? " active" : ""}`;
    button.textContent = String(page);
    button.setAttribute("aria-label", `第 ${page} 页`);
    if (page === currentPage) button.setAttribute("aria-current", "page");
    button.addEventListener("click", () => {
      currentPage = page;
      render();
    });
    return button;
  }));
}

function render() {
  const query = searchInput.value.trim().toLocaleLowerCase("zh-CN");
  const visible = PLATFORMS.filter((platform) => {
    const enabled = enabledKeys.includes(platform.key);
    const matchesFilter = activeFilter === "all" || (activeFilter === "enabled" ? enabled : !enabled);
    const haystack = `${platform.label} ${platform.key} ${platform.category}`.toLocaleLowerCase("zh-CN");
    return matchesFilter && (!query || haystack.includes(query));
  });
  const totalPages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  currentPage = Math.min(currentPage, totalPages);
  const pageStart = (currentPage - 1) * PAGE_SIZE;
  const pageItems = visible.slice(pageStart, pageStart + PAGE_SIZE);
  catalogGrid.replaceChildren(...pageItems.map(createCard));
  emptyState.hidden = visible.length > 0;
  renderPagination(visible.length, totalPages);
  updateCounts();
}

document.querySelectorAll(".filter-button").forEach((button) => {
  button.addEventListener("click", () => {
    activeFilter = button.dataset.filter;
    currentPage = 1;
    document.querySelectorAll(".filter-button").forEach((item) => item.classList.toggle("active", item === button));
    render();
  });
});
searchInput.addEventListener("input", () => {
  currentPage = 1;
  render();
});
previousPageButton.addEventListener("click", () => {
  if (currentPage === 1) return;
  currentPage -= 1;
  render();
});
nextPageButton.addEventListener("click", () => {
  currentPage += 1;
  render();
});
document.querySelector("#openGeoButton").addEventListener("click", () => chrome.tabs.create({ url: GEO_URL }));
document.querySelector("#doneButton").addEventListener("click", () => {
  chrome.tabs.getCurrent((tab) => tab?.id ? chrome.tabs.remove(tab.id) : window.close());
});

enabledKeys = await readEnabledPlatformKeys();
render();
