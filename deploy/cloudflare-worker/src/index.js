/* Lolypoly 공개 입구 (Cloudflare Worker, workers.dev 고정 주소)
 *
 * 학생 휴대폰 → https://<이름>.<계정>.workers.dev (Cloudflare HTTPS)
 *   → 이 Worker → Workers VPC 바인딩(LOLYPOLY_PC) → Cloudflare Tunnel → 강의실 PC 127.0.0.1:8000 (waitress → Django)
 *
 * - 요청을 그대로 전달하고, 원래 주소(X-Forwarded-Host)·HTTPS(X-Forwarded-Proto)·접속자 IP(X-Real-IP)를 붙인다.
 *   waitress 는 127.0.0.1(cloudflared)에서 온 이 헤더만 믿는다(deploy/windows/run_web.py).
 * - 리디렉션·쿠키·캐시 헤더는 Django 응답 그대로 돌려준다(redirect: "manual").
 * - PC·터널이 꺼져 있으면 짧은 안내 화면(503)을 보여 준다. 설치된 앱은 서비스워커가 저장한 화면을 대신 보여 준다.
 */
const ORIGIN = "http://127.0.0.1:8000";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
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
