/* Lolypoly 서비스 워커 — Django 템플릿으로 /sw.js 에서 제공 (scope: /)
 *
 * 캐시 전략
 * - 화면(HTML): 네트워크 우선 → 실패하면 마지막으로 저장한 같은 화면 → 없으면 오프라인 안내 화면
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

async function networkFirstPage(request) {
  const url = new URL(request.url);
  try {
    const response = await fetch(request);
    const type = response.headers.get("Content-Type") || "";
    if (response.ok && type.includes("text/html") && isCacheablePage(url)) {
      const cache = await caches.open(PAGE_CACHE);
      await cache.put(request, response.clone());
      trimPageCache();
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request, { cacheName: PAGE_CACHE });
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
    event.respondWith(networkFirstPage(request));
  } else if (url.pathname.startsWith("{{ static_url }}") && !url.pathname.startsWith("{{ static_url }}admin/")) {
    event.respondWith(cacheFirstStatic(request));
  }
});
