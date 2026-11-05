/* Lolypoly 최소 JavaScript
 * 1) 서비스 워커 등록 (HTTPS 또는 localhost 에서만 동작)
 * 2) 저장된(캐시) 화면 안내: 서버가 화면을 만든 시각(rendered-at)이 10분 넘게 지났으면 띠를 보여 준다.
 * 3) 앱 설치 안내 하단 시트 (아래 setupInstall 설명 참고)
 */
(function () {
  "use strict";

  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {});
    });
  }

  setupInstall();
  setupCachedBanner();

  function setupCachedBanner() {
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
  }

  /* 3) 앱 설치 안내 하단 시트
   * 기기·브라우저별 모드
   *   prompt    : Android·PC Chrome/Edge/삼성 인터넷 — beforeinstallprompt 를 받은 경우에만 '설치하기' 버튼
   *   ios       : iPhone·iPad Safari — 공유 → 홈 화면에 추가 안내 (자동 설치 API 없음)
   *   ios-other : iPhone 의 Chrome 등 — 공유 버튼 안내
   *   inapp     : 카카오톡·인스타그램·네이버 등 앱 안 브라우저 — 기본 브라우저로 열기 안내
   *   manual    : 설치 신호가 없는 브라우저 — MY 에서 직접 열었을 때만 메뉴 안내
   * 노출 규칙
   *   - 설치된 앱(standalone)으로 열면 절대 보이지 않음, 설치 기록 저장
   *   - 자동 표시: 페이지가 다 그려진 뒤, 설치 기록 없음 + '나중에' 후 14일 지남 + 이번 방문(탭)에서 아직 안 띄움
   *     · Android 계열은 브라우저가 설치 신호를 준 경우에만(이미 설치했으면 신호가 오지 않음)
   *   - MY 의 '앱 설치 방법 보기'는 위 규칙과 상관없이 언제든 연다
   */
  function setupInstall() {
    var sheet = document.getElementById("install-sheet");
    var openers = document.querySelectorAll("[data-install-open]");
    var status = document.querySelector("[data-install-status]");
    var KEY_DISMISS = "lolypoly-install-dismissed-at";
    var KEY_INSTALLED = "lolypoly-installed";
    var KEY_SESSION = "lolypoly-install-shown";
    var SNOOZE_DAYS = 14;

    function store(kind) { try { return window[kind]; } catch (e) { return null; } }
    function get(kind, key) { var s = store(kind); try { return s ? s.getItem(key) : null; } catch (e) { return null; } }
    function set(kind, key, val) { var s = store(kind); try { if (s) s.setItem(key, val); } catch (e) { /* 저장소 차단: 무시 */ } }

    var standalone = (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
      window.navigator.standalone === true;
    if (standalone) {
      set("localStorage", KEY_INSTALLED, "1");
      if (status) status.textContent = "지금 설치된 앱으로 쓰고 있어요.";
      for (var i = 0; i < openers.length; i++) openers[i].hidden = true;
      return;
    }
    if (!sheet) return;

    var ua = navigator.userAgent || "";
    var isIOS = /iphone|ipad|ipod/i.test(ua) || (/macintosh/i.test(ua) && navigator.maxTouchPoints > 1);
    var isAndroid = /android/i.test(ua);
    var inapp = detectInApp(ua);
    var iosOther = isIOS && /CriOS|FxiOS|EdgiOS|OPiOS|Whale/i.test(ua);
    var deferred = null;
    var lastFocus = null;

    function detectInApp(s) {
      if (/KAKAOTALK/i.test(s)) return "kakao";
      if (/NAVER\(inapp|inapp;.*naver/i.test(s)) return "naver";
      if (/Instagram/i.test(s)) return "instagram";
      if (/FBAN|FBAV/i.test(s)) return "facebook";
      if (/\bLine\//i.test(s)) return "line";
      if (/DaumApps|everytimeApp|; wv\)/i.test(s)) return "other";
      return null;
    }

    function showMode(mode) {
      var parts = sheet.querySelectorAll("[data-install-mode]");
      for (var i = 0; i < parts.length; i++) parts[i].hidden = parts[i].getAttribute("data-install-mode") !== mode;
    }

    function open(mode, auto) {
      showMode(mode);
      lastFocus = document.activeElement;
      sheet.hidden = false;
      document.body.classList.add("has-install-sheet");
      if (auto) set("sessionStorage", KEY_SESSION, "1");
      // 자동으로 뜰 때는 읽던 위치를 빼앗지 않도록 포커스를 옮기지 않는다. 직접 열었으면 시트로 이동.
      if (!auto) sheet.focus();
    }

    function close(snooze) {
      sheet.hidden = true;
      document.body.classList.remove("has-install-sheet");
      if (snooze) set("localStorage", KEY_DISMISS, String(Date.now()));
      if (lastFocus && document.contains(lastFocus) && lastFocus !== document.body) lastFocus.focus();
    }

    function currentMode() {
      if (inapp) return "inapp";
      if (isIOS) return iosOther ? "ios-other" : "ios";
      if (deferred) return "prompt";
      return "manual";
    }

    function mayAutoShow() {
      if (get("localStorage", KEY_INSTALLED) === "1") return false;
      if (get("sessionStorage", KEY_SESSION) === "1") return false;
      var at = Number(get("localStorage", KEY_DISMISS) || 0);
      return !at || Date.now() - at > SNOOZE_DAYS * 86400000;
    }

    // 앱 안 브라우저: 기본 브라우저로 여는 링크(카카오톡 전용 스킴, Android 는 Chrome intent)
    if (inapp) {
      var here = window.location.href;
      var ext = sheet.querySelector("[data-install-external]");
      var name = sheet.querySelector("[data-inapp-browser]");
      if (name) name.textContent = isIOS ? "Safari" : "Chrome";
      if (ext) {
        if (inapp === "kakao") {
          ext.href = "kakaotalk://web/openExternal?url=" + encodeURIComponent(here);
          ext.hidden = false;
        } else if (isAndroid) {
          ext.href = "intent://" + here.replace(/^https?:\/\//, "") + "#Intent;scheme=https;package=com.android.chrome;end";
          ext.hidden = false;
        }
      }
    }

    var copyBtn = sheet.querySelector("[data-install-copy]");
    if (copyBtn) {
      copyBtn.addEventListener("click", function () {
        var done = sheet.querySelector("[data-install-copied]");
        var url = window.location.origin + "/";
        var ok = function () { if (done) done.hidden = false; };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(url).then(ok, function () { window.prompt("이 주소를 복사해 주세요", url); });
        } else {
          window.prompt("이 주소를 복사해 주세요", url);
        }
      });
    }

    window.addEventListener("beforeinstallprompt", function (event) {
      event.preventDefault();          // 브라우저 기본 배너 대신 시트의 버튼으로 설치
      deferred = event;
      if (inapp || isIOS) return;
      if (!sheet.hidden) { showMode("prompt"); return; }
      if (document.readyState === "complete" && mayAutoShow()) {
        window.setTimeout(function () { if (sheet.hidden && deferred && mayAutoShow()) open("prompt", true); }, 800);
      }
    });

    var installBtn = sheet.querySelector("[data-install-btn]");
    installBtn.addEventListener("click", function () {
      if (!deferred) { showMode("manual"); return; }
      var ev = deferred;
      deferred = null;                 // 신호는 한 번만 쓸 수 있다
      ev.prompt();
      ev.userChoice.then(function (choice) {
        if (choice && choice.outcome === "accepted") {
          set("localStorage", KEY_INSTALLED, "1");
          close(false);
        } else {
          showMode("manual");          // 취소했으면 메뉴로 설치하는 방법을 보여 준다
        }
      });
    });

    window.addEventListener("appinstalled", function () {
      set("localStorage", KEY_INSTALLED, "1");
      deferred = null;
      close(false);
    });

    var dismissers = sheet.querySelectorAll("[data-install-dismiss]");
    for (var d = 0; d < dismissers.length; d++) {
      dismissers[d].addEventListener("click", function () { close(true); });
    }
    sheet.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); close(true); }
    });

    for (var o = 0; o < openers.length; o++) {
      openers[o].addEventListener("click", function () { open(currentMode(), false); });
    }

    // 첫 방문 자동 안내: 화면이 다 그려진 뒤 잠깐 기다렸다가. Android 계열은 설치 신호를 받은 경우에만.
    function autoShow() {
      if (!mayAutoShow()) return;
      if (inapp || isIOS) {
        window.setTimeout(function () { if (sheet.hidden && mayAutoShow()) open(currentMode(), true); }, 1200);
      } else if (deferred) {
        window.setTimeout(function () { if (sheet.hidden && deferred && mayAutoShow()) open("prompt", true); }, 800);
      }
    }
    if (document.readyState === "complete") autoShow();
    else window.addEventListener("load", autoShow);
  }
})();
