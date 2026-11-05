/* Lolypoly 서비스 워커 — Django 템플릿으로 /sw.js 에서 제공 (scope: /)
 *
 * 캐시 전략
 * - 화면(HTML): 네트워크 우선 → 4초 넘게 늦거나 실패하면 마지막으로 저장한 같은 화면 → 없으면 오프라인 안내 화면
 *   서버가 no-store/private 로 보낸 응답, 리디렉션, 오류 응답은 저장하지 않는다(개인 화면이 생겨도 공용 캐시에 남지 않게).
 *   저장 대상은 아래 CACHEABLE_PAGES 경로(쿼리 포함 최대 MAX_PAGES 개)만. 관리자(/admin/) 등은 저장하지 않는다.
 * - 정적 파일(/static/): 캐시 우선. 버전(CACHE_VERSION)이 바뀌면 이전 캐시를 지운다.
 * - 다른 사이트(공식 홈페이지 원문 링크 등)와 GET 이외 요청은 손대지 않는다.
 * 화면이 캐시에서 열렸는지는 페이지의 rendered-at 시각으로 판단해 app.js 가 안내한다.
 */
const CACHE_VERSION = "{{ cache_version }}";
const STATIC_CACHE = `lolypoly-static-${CACHE_VERSION}`;
const PAGE_CACHE = `lolypoly-pages-${CACHE_VERSION}`;
const OFFLINE_URL = "{% url 'campus:offline' %}";
const CACHEABLE_PAGES = [{% for p in cacheable_pages %}"{{ p }}"{% if not forloop.last %}, {% endif %}{% endfor %}];
const MAX_PAGES = 30;
const PRECACHE = [OFFLINE_URL{% for a in precache_assets %}, "{{ a }}"{% endfor %}];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k.startsWith("lolypoly-") && ![STATIC_CACHE, PAGE_CACHE].includes(k)).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

function isCacheablePage(url) {
  return CACHEABLE_PAGES.includes(url.pathname);
}

async function trimPageCache() {
  const cache = await caches.open(PAGE_CACHE);
  const keys = await cache.keys();
  for (const req of keys.slice(0, Math.max(0, keys.length - MAX_PAGES))) await cache.delete(req);
}

// 저장해도 되는 화면 응답인지: 공개 목록 화면 + 정상 HTML + 서버가 저장 금지(no-store/private)를 걸지 않음
function shouldStorePage(url, response) {
  if (!response.ok || response.redirected || !isCacheablePage(url)) return false;
  const type = response.headers.get("Content-Type") || "";
  const cc = (response.headers.get("Cache-Control") || "").toLowerCase();
  return type.includes("text/html") && !cc.includes("no-store") && !cc.includes("private");
}

// 화면: 네트워크 우선. 네트워크가 SLOW_MS 넘게 늦고 저장된 같은 화면이 있으면 그것을 먼저 보여 준다
// (저장된 화면에는 app.js 가 '○분 전에 저장된 화면' 띠를 띄워 최신 정보처럼 보이지 않게 한다).
const SLOW_MS = 4000;
async function networkFirstPage(event) {
  const request = event.request;
  const url = new URL(request.url);
  const network = fetch(request).then(async (response) => {
    if (shouldStorePage(url, response)) {
      const cache = await caches.open(PAGE_CACHE);
      await cache.put(request, response.clone());
      trimPageCache();
    }
    return response;
  });
  event.waitUntil(network.catch(() => {}));   // 늦게 도착한 최신 화면도 저장은 끝까지
  const cached = await caches.match(request, { cacheName: PAGE_CACHE });
  try {
    if (!cached) return await network;
    const slow = new Promise((resolve) => setTimeout(() => resolve(cached), SLOW_MS));
    return await Promise.race([network, slow]);
  } catch (err) {
    return cached || (await caches.match(OFFLINE_URL)) || Response.error();
  }
}

async function cacheFirstStatic(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) (await caches.open(STATIC_CACHE)).put(request, response.clone());
  return response;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;          // 공식 홈페이지 등 외부는 그대로
  if (url.pathname.startsWith("/admin")) return;            // 관리자 화면은 캐시하지 않음
  if (request.mode === "navigate") {
    event.respondWith(networkFirstPage(event));
  } else if (url.pathname.startsWith("{{ static_url }}") && !url.pathname.startsWith("{{ static_url }}admin/")) {
    event.respondWith(cacheFirstStatic(request));
  }
});
