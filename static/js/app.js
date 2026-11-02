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
})();
