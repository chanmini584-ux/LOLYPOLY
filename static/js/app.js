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
  setupWeekMeal();
  setupNearestBus();

  function setupCachedBanner() {
    var meta = document.querySelector('meta[name="lolypoly-rendered-at"]');
    var banner = document.getElementById("cached-banner");
    if (!meta || !banner) return;
    var fallbackReason = null;   // 서비스 워커가 저장된 화면으로 대신 보여 준 이유: offline | server | slow

    function check() {
      var rendered = new Date(Number(meta.content) * 1000);  // epoch 초 (서버 시각)
      if (isNaN(rendered)) return;
      var minutes = Math.max(0, Math.floor((Date.now() - rendered.getTime()) / 60000));
      var offline = navigator.onLine === false;
      if (minutes < 10 && !offline && !fallbackReason) { banner.hidden = true; return; }
      var ago = minutes < 1 ? "방금" : minutes < 60 ? minutes + "분 전" : minutes < 1440 ? Math.floor(minutes / 60) + "시간 전" : Math.floor(minutes / 1440) + "일 전";
      banner.querySelector("[data-ago]").textContent = ago;
      banner.querySelector("[data-offline]").hidden = !offline;
      var server = banner.querySelector("[data-server]");
      // 기기는 온라인인데 서버에 닿지 않은 경우(offline 사유)도 서버 쪽 문제로 안내한다
      if (server) server.hidden = offline || (fallbackReason !== "server" && fallbackReason !== "offline");
      var slow = banner.querySelector("[data-slow]");
      if (slow) slow.hidden = offline || fallbackReason !== "slow";
      banner.hidden = false;
    }

    // 서버가 502·503·504 를 주거나 너무 느려서 서비스 워커가 저장된 화면을 대신 보여 줬는지 물어본다
    function askServiceWorker() {
      var sw = navigator.serviceWorker && navigator.serviceWorker.controller;
      if (!sw || !window.MessageChannel) return;
      var channel = new MessageChannel();
      channel.port1.onmessage = function (event) {
        fallbackReason = event.data && event.data.reason;
        if (fallbackReason) check();
      };
      sw.postMessage({ type: "lolypoly-fallback?", path: window.location.pathname + window.location.search }, [channel.port2]);
    }

    check();
    askServiceWorker();
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
   *   - 설치된 앱(standalone)으로 열면 절대 보이지 않음, 설치 기록(시각) 저장
   *   - 자동 표시: 페이지가 다 그려진 뒤, 최근 설치 기록 없음 + '나중에' 후 14일 지남 + 이번 방문(탭)에서 아직 안 띄움
   *     · Android 계열은 브라우저가 설치 신호를 준 경우에만(이미 설치했으면 신호가 오지 않음)
   *   - 설치 기록이 다시 설치를 영영 막지 않게(D-064):
   *     · 브라우저가 설치 신호(beforeinstallprompt)를 다시 줬다 = 지금은 설치돼 있지 않다 → 설치 기록을 지운다
   *     · 신호가 없는 iOS 는 설치 기록을 30일 동안만 믿는다(앱을 지운 사람이 다시 안내를 받을 수 있게)
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
    var INSTALLED_TRUST_DAYS = 30;

    function del(kind, key) { var s = store(kind); try { if (s) s.removeItem(key); } catch (e) { /* 무시 */ } }
    function markInstalled() { set("localStorage", KEY_INSTALLED, String(Date.now())); }
    // 예전 버전은 "1"(시각 없음)로 저장했다. 시각이 없으면 오래된 기록으로 본다.
    function installedRecently() {
      var at = Number(get("localStorage", KEY_INSTALLED) || 0);
      return at > 1 && Date.now() - at < INSTALLED_TRUST_DAYS * 86400000;
    }
    function store(kind) { try { return window[kind]; } catch (e) { return null; } }
    function get(kind, key) { var s = store(kind); try { return s ? s.getItem(key) : null; } catch (e) { return null; } }
    function set(kind, key, val) { var s = store(kind); try { if (s) s.setItem(key, val); } catch (e) { /* 저장소 차단: 무시 */ } }

    var standalone = (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
      window.navigator.standalone === true;
    if (standalone) {
      markInstalled();
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
      if (installedRecently()) return false;
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
      del("localStorage", KEY_INSTALLED);   // 설치 신호가 왔다 = 지금은 설치돼 있지 않다(예전 설치 기록 무효)
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
          markInstalled();
          close(false);
        } else {
          showMode("manual");          // 취소했으면 메뉴로 설치하는 방법을 보여 준다
        }
      });
    });

    window.addEventListener("appinstalled", function () {
      markInstalled();
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

  /* 4) 홈 '이번 주 밥': 요일 동그라미를 누르면 새로고침 없이 그날 메모로 바꾼다.
   *    JS가 없으면 링크(?day=)로 같은 화면을 다시 불러온다. */
  function setupWeekMeal() {
    var dots = document.querySelector("[data-week-dots]");
    if (!dots) return;
    dots.addEventListener("click", function (event) {
      var link = event.target.closest("[data-day]");
      if (!link) return;
      var panel = document.querySelector('[data-day-panel="' + link.getAttribute("data-day") + '"]');
      if (!panel) return;
      event.preventDefault();
      Array.prototype.forEach.call(document.querySelectorAll("[data-day-panel]"), function (p) { p.hidden = p !== panel; });
      Array.prototype.forEach.call(dots.querySelectorAll("[data-day]"), function (a) {
        if (a === link) a.setAttribute("aria-current", "date"); else a.removeAttribute("aria-current");
      });
    });
  }

  /* 5) 홈 '학교 가는 버스': 홈을 열 때(와 다시 볼 때) 한 번만 가장 가까운 버스를 불러온다.
   *    서버는 폴리텍대학 정류장 도착정보를 1번만 부르고 1분 캐시. 계속 움직이는 화면은 버스 화면(bus.js)에서. */
  function setupNearestBus() {
    var box = document.querySelector("[data-bus-nearest]");
    if (!box || !window.fetch) return;
    var text = box.querySelector("[data-bus-text]");
    var away = box.querySelector("[data-bus-away]");
    var meta = document.querySelector("[data-bus-meta]");
    var last = 0;
    function load() {
      if (Date.now() - last < 60000) return;
      last = Date.now();
      fetch(box.getAttribute("data-bus-nearest"), { headers: { Accept: "application/json" }, cache: "no-store" })
        .then(function (res) { return res.json(); })
        .then(function (data) {
          var bus = data.bus;
          if (bus) {
            text.innerHTML = "";
            var b = document.createElement("b");
            b.textContent = bus.group;
            text.appendChild(b);
            text.appendChild(document.createTextNode(" 약 " + bus.minutes + "분 뒤 폴리텍대학"));
            away.textContent = bus.away <= 0 ? "곧 도착" : bus.away + "정거장 전";
            away.hidden = false;
            meta.textContent = data.updated + " 기준 · 폴리텍대학(학교 가는 쪽)에 가장 먼저 오는 버스";
          } else {
            text.textContent = data.message || "실시간 위치를 불러오지 못했어요.";
            away.hidden = true;
            meta.textContent = "눌러서 노선별 버스 보기";
          }
        })
        .catch(function () { text.textContent = "실시간 위치를 불러오지 못했어요."; });
    }
    load();
    document.addEventListener("visibilitychange", function () { if (!document.hidden) load(); });
  }
})();
