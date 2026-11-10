/* Lolypoly 버스 화면: 노선 줄그림 위에 실시간 버스 위치를 그린다.
 *
 * - 서버(/bus/live/<노선>/)에서 칸별 버스 위치(pos = 줄그림의 몇 번째 정류장)를 받아 버스 아이콘을 옮긴다.
 *   같은 버스(차량 번호 기준)는 같은 아이콘이 미끄러지듯 이동한다(CSS transition).
 * - 30초마다 갱신. 화면이 숨겨지면 멈추고, 다시 보이면 바로 갱신. 10분 지나면 자동 갱신을 멈추고 버튼을 보여 준다.
 * - 서버가 30초 캐시를 두므로 여러 명이 보고 있어도 TAGO 호출은 늘지 않는다.
 */
(function () {
  "use strict";

  var root = document.querySelector("[data-bus-live]");
  if (!root || root.getAttribute("data-enabled") !== "1" || !window.fetch) return;

  var POLL_MS = 30000;
  var MAX_POLLS = 20;  // 30초 × 20 = 10분
  var url = root.getAttribute("data-url");
  var statusEl = root.querySelector("[data-live-status]");
  var refreshBtn = root.querySelector("[data-live-refresh]");
  var timer = null;
  var polls = 0;
  var lastData = null;
  var resizeTimer = null;

  var BUS_SVG = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
    '<rect x="4" y="3" width="16" height="15" rx="3"/><path d="M4 11h16M8 21v-3M16 21v-3"/>' +
    '<circle cx="8" cy="14.5" r="1"/><circle cx="16" cy="14.5" r="1"/></svg>';

  function awayText(away) {
    if (away > 0) return away + "정거장 전";
    if (away === 0) return "학교 정류장";
    return "지나감";
  }

  function setStatus(text) { statusEl.textContent = text; }

  function rowCenter(panel, pos) {
    var li = panel.querySelector('.route-stop[data-index="' + pos + '"]');
    return li ? li.offsetTop + li.offsetHeight / 2 : null;
  }

  function renderPanel(panel, data) {
    var layer = panel.querySelector("[data-layer]");
    var buses = (data && data.buses) || [];
    var far = (data && data.far) || [];

    // 같은 정류장의 버스는 아이콘 하나로 묶는다
    var byPos = {};
    buses.forEach(function (b) { (byPos[b.pos] = byPos[b.pos] || []).push(b); });

    var keep = {};
    Object.keys(byPos).forEach(function (pos) {
      var group = byPos[pos];
      var key = group.map(function (b) { return b.id; }).sort().join("|");
      var y = rowCenter(panel, pos);
      if (y === null) return;
      var marker = layer.querySelector('[data-key="' + CSS.escape(key) + '"]');
      if (!marker) {
        // 한 대만 있던 아이콘이 있으면 그 아이콘을 재사용해 '이동'처럼 보이게 한다
        marker = group.length === 1 ? layer.querySelector('[data-id="' + CSS.escape(group[0].id) + '"]') : null;
      }
      if (!marker) {
        marker = document.createElement("div");
        marker.className = "bus-marker";
        marker.innerHTML = '<span class="bus-marker__icon">' + BUS_SVG + '</span><span class="bus-marker__label"></span>';
        marker.style.transform = "translateY(" + y + "px)";
        layer.appendChild(marker);
      }
      marker.setAttribute("data-key", key);
      marker.setAttribute("data-id", group.length === 1 ? group[0].id : "");
      marker.title = group.map(function (b) { return b.route; }).join(", ");
      var min = Math.min.apply(null, group.map(function (b) { return b.away; }));
      marker.querySelector(".bus-marker__label").textContent =
        (group.length > 1 ? group.length + "대 · " : "") + awayText(min);
      marker.classList.toggle("bus-marker--school", min === 0);
      // 새로 그린 뒤 다음 프레임에 위치를 바꿔야 transition 이 적용된다
      requestAnimationFrame(function () { marker.style.transform = "translateY(" + y + "px)"; });
      keep[key] = true;
    });
    Array.prototype.forEach.call(layer.querySelectorAll(".bus-marker"), function (m) {
      if (!keep[m.getAttribute("data-key")]) m.remove();
    });

    var farEl = panel.querySelector("[data-far]");
    if (far.length) {
      var first = far[0];
      farEl.textContent = "더 먼 곳에서 오는 버스: " + first.stop + " 부근(" + awayText(first.away) + ")" +
        (far.length > 1 ? " 외 " + (far.length - 1) + "대" : "");
      farEl.hidden = false;
    } else {
      farEl.hidden = true;
    }

    var summary = panel.querySelector("[data-summary]");
    var title = panel.querySelector(".card__title").textContent;
    var parts = buses.map(function (b) { return b.stop + "에 1대, " + awayText(b.away); });
    var text = title + ": " + (parts.length ? parts.join(". ") : "학교 근처 구간에 버스 없음");
    if (summary.textContent !== text) summary.textContent = text;
    return buses.length + far.length;
  }

  function render(data) {
    lastData = data;
    var total = 0;
    Array.prototype.forEach.call(root.querySelectorAll("[data-panel]"), function (panel) {
      total += renderPanel(panel, data.panels && data.panels[panel.getAttribute("data-panel")]);
    });
    if (data.quiet) {
      setStatus(data.message);
    } else if (!data.ok) {
      setStatus(data.message || "실시간 위치를 불러오지 못했어요.");
    } else {
      var text = data.updated + " 기준";
      if (data.delayed) text = data.message;
      else if (!total) text += " · 지금 이 노선에서 학교 쪽으로 오는 버스가 없어요";
      else text += " · 30초마다 갱신";
      setStatus(text);
    }
  }

  function load() {
    fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" })
      .then(function (res) { return res.json(); })
      .then(render)
      .catch(function () { setStatus("실시간 위치를 불러오지 못했어요. 인터넷 연결을 확인해 주세요."); });
  }

  function schedule() {
    clearTimeout(timer);
    if (document.hidden) return;
    if (polls >= MAX_POLLS) {
      refreshBtn.hidden = false;
      setStatus(statusEl.textContent.replace(/ · 30초마다 갱신$/, "") + " · 자동 갱신을 멈췄어요");
      return;
    }
    timer = setTimeout(function () { polls += 1; load(); schedule(); }, POLL_MS);
  }

  refreshBtn.addEventListener("click", function () {
    polls = 0;
    refreshBtn.hidden = true;
    load();
    schedule();
  });
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && polls < MAX_POLLS) { load(); }
    schedule();
  });
  // 글자 크기·화면 폭이 바뀌면 정류장 줄 위치가 바뀌므로 다시 그린다
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { if (lastData) render(lastData); }, 200);
  });

  load();
  schedule();
})();
