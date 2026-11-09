/* Lolypoly 서비스 워커 — Django 템플릿으로 /sw.js 에서 제공 (scope: /)
 *
 * 캐시 전략
 * - 화면(HTML): 네트워크 우선 → 실패하면 마지막으로 저장한 같은 화면 → 없으면 오프라인 안내 화면
 *   저장 대상은 아래 CACHEABLE_PAGES 경로(쿼리 포함 최대 MAX_PAGES 개)만. 관리자(/admin/) 등은 저장하지 않는다.
 *   같은 화면 찾기: 주소(쿼리 포함)가 같은 것 → 없으면 경로만 같은 것(예: /?source=pwa 와 /).
 * - 서버가 깨어나는 중일 때(D-043): 무료 호스팅은 잠들었다 깨어날 때 자기 '대기 화면'을 먼저 보내고 1분 가까이 걸린다.
 *   ① 응답에 X-Lolypoly 헤더가 없으면 우리 앱 화면이 아니므로 저장하지 않고, 저장된 화면이 있으면 그것을 보여 준다.
 *   ② NETWORK_WAIT_MS 안에 응답이 없으면 저장된 화면을 먼저 보여 주고, 네트워크 응답은 뒤에서 저장만 한다.
 *   저장된 화면이 없으면 기다렸다가 서버(또는 호스팅) 응답을 그대로 보여 준다.
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
const NETWORK_WAIT_MS = 4000;   // 이보다 늦으면 저장된 화면을 먼저 보여 준다
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

function isAppResponse(response) {
  return response.headers.get("X-Lolypoly") === "1";
}

async function cachedPage(request) {
  const cache = await caches.open(PAGE_CACHE);
  return (await cache.match(request)) || (await cache.match(request, { ignoreSearch: true }));
}

async function savePage(request, response) {
  const type = response.headers.get("Content-Type") || "";
  if (!response.ok || !isAppResponse(response) || !type.includes("text/html")) return;
  if (!isCacheablePage(new URL(request.url))) return;
  const cache = await caches.open(PAGE_CACHE);
  await cache.put(request, response.clone());
  await trimPageCache();
}

async function networkFirstPage(event) {
  const request = event.request;
  const network = fetch(request).then(async (response) => {
    await savePage(request, response);
    return response;
  });
  event.waitUntil(network.catch(() => {}));   // 저장된 화면을 먼저 보여 줘도 응답은 끝까지 받아 저장한다

  let timer;
  const timeout = new Promise((resolve) => { timer = setTimeout(() => resolve(null), NETWORK_WAIT_MS); });
  let first;
  try {
    first = await Promise.race([network, timeout]);
  } catch (err) {
    clearTimeout(timer);
    return (await cachedPage(request)) || (await caches.match(OFFLINE_URL)) || Response.error();
  }
  clearTimeout(timer);

  // 우리 앱 응답(404 포함)이나 이동(redirect)은 그대로 보여 준다
  if (first && (isAppResponse(first) || first.type === "opaqueredirect")) return first;
  // 늦거나(first=null) 호스팅 대기 화면이면 저장된 화면 먼저
  const cached = await cachedPage(request);
  if (cached) return cached;
  if (first) return first;
  try {
    return await network;
  } catch (err) {
    return (await caches.match(OFFLINE_URL)) || Response.error();
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
