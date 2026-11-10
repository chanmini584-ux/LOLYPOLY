/* Lolypoly 서비스 워커 — Django 템플릿으로 /sw.js 에서 제공 (scope: /)
 *
 * 무엇을 저장하나
 * - 공개 화면(HTML)만: 아래 CACHEABLE_PAGES 경로(홈·식단·학사일정·공지·버스). 쿼리 포함 최대 MAX_PAGES 개.
 *   저장 조건: 우리 앱이 만든 응답(X-Lolypoly 헤더) + 200 + HTML + 리디렉션 아님 + 서버가 no-store/private 를 걸지 않음.
 * - 로그인해야 보이는 화면(커뮤니티·계정·MY·알림·보호된 사진·관리자)은 절대 저장하지 않는다.
 *   서버도 이 화면들에 'no-store, private' 를 붙인다(이중 안전장치).
 * - 정적 파일(/static/): 캐시 우선. 버전(CACHE_VERSION)이 바뀌면 이전 캐시를 모두 지운다.
 *
 * 화면(HTML) 요청 처리 — 네트워크 우선
 * ① 정상 응답은 그대로 보여 준다. 401·403·404 등 우리 앱이 보낸 오류·접근 제한 응답도 그대로 보여 준다
 *    (저장된 화면으로 접근 제한을 돌아가지 않는다).
 * ② 서버 쪽 장애일 때는 저장된 '같은 공개 화면'으로 대신한다(D-063):
 *    - 통신 단절, - NETWORK_WAIT_MS 넘게 느림, - 502·503·504(학교 PC·터널이 꺼짐), - 호스팅 대기 화면(X-Lolypoly 없음, D-055).
 *    저장된 화면이 없으면 서버 응답(안내 화면)을 그대로, 통신 단절이면 오프라인 안내 화면을 보여 준다.
 * ③ 저장된 화면으로 대신했다는 사실과 이유를 기억해 두었다가 페이지(app.js)가 물어보면 알려 준다 → 화면 위 안내 띠.
 * - 다른 사이트(공식 홈페이지 원문 링크 등)와 GET 이외 요청은 손대지 않는다.
 */
const CACHE_VERSION = "{{ cache_version }}";
const STATIC_CACHE = `lolypoly-static-${CACHE_VERSION}`;
const PAGE_CACHE = `lolypoly-pages-${CACHE_VERSION}`;
const OFFLINE_URL = "{% url 'campus:offline' %}";
const CACHEABLE_PAGES = [{% for p in cacheable_pages %}"{{ p }}"{% if not forloop.last %}, {% endif %}{% endfor %}];
const MAX_PAGES = 30;
const NETWORK_WAIT_MS = 4000;   // 이보다 늦으면 저장된 화면을 먼저 보여 준다
const SERVER_DOWN = [502, 503, 504];
const PRECACHE = [OFFLINE_URL{% for a in precache_assets %}, "{{ a }}"{% endfor %}];
const fallbacks = new Map();    // 주소 → {reason, at}: 방금 저장된 화면으로 대신한 기록

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

function isAppResponse(response) {
  return response.headers.get("X-Lolypoly") === "1";
}

async function trimPageCache() {
  const cache = await caches.open(PAGE_CACHE);
  const keys = await cache.keys();
  for (const req of keys.slice(0, Math.max(0, keys.length - MAX_PAGES))) await cache.delete(req);
}

// 저장해도 되는 화면 응답인지
function shouldStorePage(url, response) {
  if (!isCacheablePage(url) || response.status !== 200 || response.redirected || !isAppResponse(response)) return false;
  const type = response.headers.get("Content-Type") || "";
  const cc = (response.headers.get("Cache-Control") || "").toLowerCase();
  return type.includes("text/html") && !cc.includes("no-store") && !cc.includes("private");
}

// 저장된 같은 공개 화면: 주소(쿼리 포함)가 같은 것 → 없으면 경로만 같은 것. 공개 화면 경로가 아니면 찾지 않는다.
async function cachedPage(request, url) {
  if (!isCacheablePage(url)) return null;
  const cache = await caches.open(PAGE_CACHE);
  return (await cache.match(request)) || (await cache.match(request, { ignoreSearch: true })) || null;
}

function remember(url, reason) {
  fallbacks.set(url.pathname + url.search, { reason, at: Date.now() });
  for (const [key, value] of fallbacks) if (Date.now() - value.at > 60000) fallbacks.delete(key);
}

async function networkFirstPage(event) {
  const request = event.request;
  const url = new URL(request.url);
  const network = fetch(request).then(async (response) => {
    if (shouldStorePage(url, response)) {
      const cache = await caches.open(PAGE_CACHE);
      await cache.put(request, response.clone());
      await trimPageCache();
    }
    return response;
  });
  event.waitUntil(network.catch(() => {}));   // 저장된 화면을 먼저 보여 줘도 응답은 끝까지 받아 저장한다

  let timer;
  const timeout = new Promise((resolve) => { timer = setTimeout(() => resolve(null), NETWORK_WAIT_MS); });
  let first;
  try {
    first = await Promise.race([network, timeout]);
  } catch (err) {                               // 통신 단절
    clearTimeout(timer);
    const cached = await cachedPage(request, url);
    if (cached) { remember(url, "offline"); return cached; }
    return (await caches.match(OFFLINE_URL)) || Response.error();
  }
  clearTimeout(timer);

  if (first) {
    const down = SERVER_DOWN.includes(first.status) || (!isAppResponse(first) && first.type !== "opaqueredirect");
    if (!down) { fallbacks.delete(url.pathname + url.search); return first; }   // 정상·리디렉션·401·403·404 등은 그대로(예전 대체 기록은 지움)
    const cached = await cachedPage(request, url);
    if (cached) { remember(url, "server"); return cached; }
    return first;                               // 저장된 화면이 없으면 서버 안내 화면 그대로
  }
  // 느림
  const cached = await cachedPage(request, url);
  if (cached) { remember(url, "slow"); return cached; }
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
  if (url.pathname.startsWith("/admin")) return;            // 관리자 화면은 손대지 않음
  if (request.mode === "navigate") {
    event.respondWith(networkFirstPage(event));
  } else if (url.pathname.startsWith("{{ static_url }}") && !url.pathname.startsWith("{{ static_url }}admin/")) {
    event.respondWith(cacheFirstStatic(request));
  }
  // 그 밖(보호된 사진, 실시간 버스 JSON 등)은 브라우저가 서버에 직접 요청한다 — 저장하지 않는다.
});

// 페이지가 "이 화면, 저장된 걸로 대신 보여 준 거야?" 하고 물으면 이유를 알려 준다
self.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type !== "lolypoly-fallback?" || !event.ports || !event.ports[0]) return;
  const hit = fallbacks.get(data.path);
  event.ports[0].postMessage(hit && Date.now() - hit.at < 30000 ? { reason: hit.reason } : { reason: null });
});
