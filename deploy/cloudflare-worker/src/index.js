/* Lolypoly 공개 입구 (Cloudflare Worker, workers.dev 고정 주소)
 *
 * 학생 휴대폰 → https://<이름>.<계정>.workers.dev (Cloudflare HTTPS)
 *   → 이 Worker → Workers VPC 바인딩(LOLYPOLY_PC) → Cloudflare Tunnel → 강의실 PC 127.0.0.1:8000 (waitress → Django)
 *
 * - 요청을 그대로 전달하고, 원래 주소(X-Forwarded-Host)·HTTPS(X-Forwarded-Proto)·접속자 IP(X-Real-IP)를 붙인다.
 *   waitress 는 127.0.0.1(cloudflared)에서 온 이 헤더만 믿는다(deploy/windows/run_web.py).
 * - 리디렉션·쿠키·캐시 헤더는 Django 응답 그대로 돌려준다(redirect: "manual").
 * - PC·터널이 꺼져 있으면 짧은 안내 화면(503)을 보여 준다. 설치된 앱은 서비스워커가 저장한 화면을 대신 보여 준다.
 *
 * 공통 RAG 엔진 공개 경로(엔진 v0.6.0, MARU 아리용):
 *   방문객 브라우저 → https://<이 Worker>/rag/v1/public/chat → 바인딩 RAG_ENGINE → 같은 PC의 엔진 127.0.0.1:8088/v1/public/chat
 * - 열어 두는 것은 POST(와 CORS 사전 요청 OPTIONS) /rag/v1/public/chat 하나뿐. /rag/ 아래 다른 주소(/v1/chat 앱 키 경로, /health 등)는
 *   엔진에 보내지 않고 404. 롤리폴리 서버→엔진 호출은 같은 PC 안(127.0.0.1)이라 이 Worker를 지나지 않는다.
 * - X-Forwarded-For 는 방문객이 보낸 값을 버리고 Cloudflare 가 본 접속 IP 하나로 바꾼다 → 엔진 RAG_TRUST_PROXY_HOPS=1 이 이 값을 쓴다.
 * - CORS 판정(Origin 허용 여부)과 요청 제한(429·Retry-After)은 엔진이 한다(RAG_PUBLIC_ORIGINS, RAG_PUBLIC_RATE_PER_MIN). Worker 는 그대로 전달.
 * - RAG_ENGINE 바인딩이 없으면(아직 VPC 서비스를 안 만듦) 503. 로컬 시험(wrangler dev)만 .dev.vars 의 RAG_DEV_ORIGIN 으로 보낸다.
 */
const ORIGIN = "http://127.0.0.1:8000";
const RAG_PREFIX = "/rag/";
const RAG_PUBLIC_PATH = "/rag/v1/public/chat";
const RAG_ORIGIN = "http://127.0.0.1:8088";
const RAG_MAX_BODY = 8192;   // 질문 한 개(JSON)면 충분. 큰 본문은 엔진까지 보내지 않는다

async function ragProxy(request, env, url) {
  const json = (status, body, extra = {}) => new Response(JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...extra } });
  if (url.pathname !== RAG_PUBLIC_PATH) return json(404, { error: "not_found" });
  if (request.method !== "POST" && request.method !== "OPTIONS") return json(405, { error: "method_not_allowed" }, { Allow: "POST, OPTIONS" });
  const len = Number(request.headers.get("Content-Length") || 0);
  if (len > RAG_MAX_BODY) return json(413, { error: "too_large" });
  const headers = new Headers();
  for (const h of ["Content-Type", "Origin", "Accept", "Accept-Language", "Access-Control-Request-Method", "Access-Control-Request-Headers"]) {
    const v = request.headers.get(h);
    if (v) headers.set(h, v);
  }
  const ip = request.headers.get("CF-Connecting-IP");
  if (ip) headers.set("X-Forwarded-For", ip);
  const init = { method: request.method, headers, redirect: "manual" };
  if (request.method === "POST") {
    const body = await request.arrayBuffer();
    if (body.byteLength > RAG_MAX_BODY) return json(413, { error: "too_large" });
    init.body = body;
  }
  const path = "/v1/public/chat" + url.search;
  try {
    if (env.RAG_ENGINE) return await env.RAG_ENGINE.fetch(new Request(new URL(path, RAG_ORIGIN), init));
    if (env.RAG_DEV_ORIGIN) return await fetch(new Request(new URL(path, env.RAG_DEV_ORIGIN), init));   // wrangler dev 전용
    return json(503, { error: "rag_not_configured", message: "안내 엔진 경로가 아직 설정되지 않았어요." }, { "Retry-After": "300" });
  } catch (err) {
    return json(503, { error: "engine_unreachable", message: "안내 엔진에 잠시 연결할 수 없어요." }, { "Retry-After": "60" });
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith(RAG_PREFIX)) return ragProxy(request, env, url);
    const target = new URL(url.pathname + url.search, ORIGIN);
    const headers = new Headers(request.headers);
    headers.set("X-Forwarded-Host", url.host);
    headers.set("X-Forwarded-Proto", "https");
    const ip = request.headers.get("CF-Connecting-IP");
    if (ip) headers.set("X-Real-IP", ip);
    const init = { method: request.method, headers, redirect: "manual" };
    if (request.method !== "GET" && request.method !== "HEAD") init.body = request.body;
    try {
      return await env.LOLYPOLY_PC.fetch(new Request(target, init));
    } catch (err) {
      return new Response(DOWN_HTML, {
        status: 503,
        headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", "Retry-After": "120" },
      });
    }
  },
};

const DOWN_HTML = `<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>잠시 연결이 안 돼요 · Lolypoly</title>
<style>body{margin:0;font-family:-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;background:#fff;color:#1e1e1e;
display:flex;min-height:100vh;align-items:center;justify-content:center;text-align:center;padding:24px}
h1{color:#2a46b8;font-size:24px}a{color:#2a46b8;font-weight:700}</style></head><body><main>
<h1>Lolypoly 서버에 잠시 연결할 수 없어요</h1>
<p>점검 중이거나 서버 컴퓨터가 꺼져 있어요. 잠시 뒤 다시 열어 주세요.</p>
<p>급한 정보는 <a href="https://www.kopo.ac.kr/chuncheon/index.do">학교 공식 홈페이지</a>에서 확인해 주세요.</p>
</main></body></html>`;
