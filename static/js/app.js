/* Lolypoly 최소 JavaScript
 * 1) 서비스 워커 등록 (HTTPS 또는 localhost 에서만 동작)
 * 2) 저장된(캐시) 화면 안내: 서버가 화면을 만든 시각(rendered-at)이 10분 넘게 지났으면
 *    '저장된 화면'이라는 띠를 보여준다. 오프라인에서 캐시로 열린 경우가 여기에 해당한다.
 */
(function () {
  "use strict";

  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {});
    });
  }

  setupInstallCard();

  var meta = document.querySelector('meta[name="lolypoly-rendered-at"]');
  var banner = document.getElementById("cached-banner");
  if (!meta || !banner) return;

  function check() {
    var rendered = new Date(Number(meta.content) * 1000);  // epoch 초 (서버 시각)
    if (isNaN(rendered)) return;
    var minutes = Math.floor((Date.now() - rendered.getTime()) / 60000);
    var offline = navigator.onLine === false;
    if (minutes < 10 && !offline) { banner.hidden = true; return; }
    var ago = minutes < 60 ? minutes + "분" : minutes < 1440 ? Math.floor(minutes / 60) + "시간" : Math.floor(minutes / 1440) + "일";
    banner.querySelector("[data-ago]").textContent = ago;
    banner.querySelector("[data-offline]").hidden = !offline;
    banner.hidden = false;
  }

  check();
  window.addEventListener("online", check);
  window.addEventListener("offline", check);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) check(); });

  /* 3) 앱 설치 안내 카드 (홈·MY)
   * - Android·PC Chrome 등: 브라우저가 beforeinstallprompt를 주면 '앱 설치' 버튼 한 번으로 설치
   * - iPhone·iPad: 설치 버튼 API가 없어 '공유 → 홈 화면에 추가' 안내
   * - 그 밖의 브라우저: MY 화면에서만 메뉴 안내
   * - 이미 설치된 앱으로 열었으면 카드를 보여 주지 않음
   * - 홈에서 '다음에 할게요'를 누르면 이 브라우저에서는 홈 카드만 숨김(MY에서는 계속 보임)
   * - 주소에 ?install=1이 있으면(설치용 QR) 숨김 기록을 무시하고 안내를 보여 줌
   */
  function setupInstallCard() {
    var card = document.getElementById("install-card");
    if (!card) return;
    var standalone = (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
      window.navigator.standalone === true;
    if (standalone) return;

    var DISMISS_KEY = "lolypoly-install-dismissed";
    var onHome = card.getAttribute("data-page") === "home";
    var dismissed = false;
    try { dismissed = window.localStorage.getItem(DISMISS_KEY) === "1"; } catch (e) { /* 저장소 차단: 무시 */ }
    // QR 주소(?install=1)로 열면 '다음에 할게요'를 눌렀던 브라우저에서도 카드를 다시 보여 준다
    var forced = /[?&]install=1(&|$)/.test(window.location.search);
    if (onHome && dismissed && !forced) return;

    var btn = card.querySelector("[data-install-btn]");
    var ios = card.querySelector("[data-install-ios]");
    var generic = card.querySelector("[data-install-generic]");
    var close = card.querySelector("[data-install-close]");
    var deferred = null;

    var ua = navigator.userAgent || "";
    var isIOS = /iphone|ipad|ipod/i.test(ua) || (/macintosh/i.test(ua) && navigator.maxTouchPoints > 1);
    if (isIOS) { ios.hidden = false; card.hidden = false; }

    window.addEventListener("beforeinstallprompt", function (event) {
      event.preventDefault();          // 브라우저 기본 배너 대신 카드의 버튼으로 설치
      deferred = event;
      btn.hidden = false;
      if (generic) generic.hidden = true;
      card.hidden = false;
    });

    btn.addEventListener("click", function () {
      if (!deferred) return;
      deferred.prompt();
      deferred.userChoice.then(function (choice) {
        if (choice && choice.outcome === "accepted") card.hidden = true;
        deferred = null;
        btn.hidden = true;
      });
    });

    window.addEventListener("appinstalled", function () { card.hidden = true; });

    if (close) {
      close.addEventListener("click", function () {
        card.hidden = true;
        try { window.localStorage.setItem(DISMISS_KEY, "1"); } catch (e) { /* 무시 */ }
      });
    }

    // MY 화면: 설치 버튼 신호가 없는 브라우저(파이어폭스 등)에도 메뉴 안내를 보여 준다
    if ((!onHome || forced) && !isIOS && generic) {
      window.setTimeout(function () {
        if (!deferred) { generic.hidden = false; card.hidden = false; }
      }, 2500);
    }
  }
})();
