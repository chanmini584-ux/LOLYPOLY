/* Lolypoly 번개 택시방 (D-070·D-071)
 * 1) 방 만들기: '자주 쓰는 곳' 버튼 → 마지막으로 누른 칸(출발지/도착지)에 넣기
 * 2) 채팅방: 3초마다 새 메시지만 받아 붙이기(?after=마지막 번호), 새로고침 없이 보내기,
 *    화면이 숨겨지면 멈춤, 방이 닫히면 안내 후 목록으로. JS 가 없으면 보내기 폼이 새로고침으로 동작한다.
 */
(function () {
  "use strict";

  // 1) 자주 쓰는 곳
  var origin = document.getElementById("id_origin");
  var dest = document.getElementById("id_destination");
  if (origin && dest) {
    var last = null;
    [origin, dest].forEach(function (el) { el.addEventListener("focus", function () { last = el; }); });
    Array.prototype.forEach.call(document.querySelectorAll("[data-place]"), function (b) {
      b.addEventListener("click", function () {
        var target = last || (!origin.value ? origin : dest);
        target.value = b.getAttribute("data-place");
        last = target === origin ? dest : origin;
      });
    });
  }

  // 2) 채팅방
  var box = document.querySelector("[data-taxi-room]");
  if (!box || !window.fetch) return;
  var url = box.getAttribute("data-url");
  var listUrl = box.getAttribute("data-list");
  var reportUrl = box.getAttribute("data-report");      // .../m/0/report/ → 0 을 메시지 번호로 바꿔 쓴다
  var lastId = Number(box.getAttribute("data-last")) || 0;
  var form = document.querySelector("[data-taxi-form]");
  var input = form.querySelector("input[name=body]");
  var status = document.querySelector("[data-taxi-status]");
  var baseStatus = status.textContent;
  var members = document.querySelector("[data-taxi-members]");
  var countEl = document.querySelector("[data-taxi-count]");
  var timer = null;
  var busy = false;

  function nearBottom() { return window.innerHeight + window.scrollY >= document.body.scrollHeight - 160; }

  function add(m) {
    var el;
    if (m.system) {
      el = document.createElement("p");
      el.className = "taxi-sys";
      el.textContent = m.body;
    } else {
      el = document.createElement("div");
      el.className = "taxi-msg" + (m.mine ? " is-mine" : "");
      var who = document.createElement("span");
      who.className = "taxi-msg__who";
      who.textContent = (m.mine ? "나" : m.who) + " · " + m.time;
      var body = document.createElement("p");
      body.className = "taxi-msg__body" + (m.blocked ? " is-blocked" : "");
      body.textContent = m.body;
      el.appendChild(who);
      el.appendChild(body);
      if (!m.mine && !m.blocked) {
        var r = document.createElement("a");
        r.className = "taxi-msg__report";
        r.href = reportUrl.replace("/m/0/", "/m/" + m.id + "/");
        r.textContent = "신고";
        el.appendChild(r);
      }
    }
    box.insertBefore(el, document.getElementById("chat-end"));
  }

  function renderMembers(list) {
    members.innerHTML = "";
    list.forEach(function (m) {
      var li = document.createElement("li");
      li.className = (m.host ? "is-host" : "") + (m.me ? " is-me" : "");
      li.textContent = m.label + (m.me ? " (나)" : "");
      members.appendChild(li);
    });
  }

  function poll() {
    if (busy) return;
    busy = true;
    fetch(url + "?after=" + lastId, { headers: { Accept: "application/json" }, cache: "no-store", credentials: "same-origin" })
      .then(function (res) {
        if (res.status === 403) throw new Error("left");
        return res.json();
      })
      .then(function (data) {
        if (data.closed) {
          stop();
          status.textContent = "방이 닫혔어요. 목록으로 돌아갈게요.";
          setTimeout(function () { window.location.href = listUrl; }, 1500);
          return;
        }
        var stick = nearBottom();
        data.messages.forEach(function (m) { if (m.id > lastId) { add(m); lastId = m.id; } });
        renderMembers(data.members);
        if (countEl) countEl.textContent = data.count;
        status.textContent = baseStatus;
        if (stick && data.messages.length) window.scrollTo(0, document.body.scrollHeight);
      })
      .catch(function (err) {
        if (err && err.message === "left") { stop(); window.location.href = listUrl; return; }
        status.textContent = "연결이 잠시 끊겼어요. 다시 확인하는 중이에요…";
      })
      .then(function () { busy = false; });
  }

  function start() { if (!timer) timer = setInterval(poll, 3000); }
  function stop() { clearInterval(timer); timer = null; }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var text = input.value.trim();
    if (!text) return;
    var data = new FormData(form);
    fetch(form.action, { method: "POST", body: data, headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (res) { return res.json(); })
      .then(function (r) {
        if (r.ok) { input.value = ""; poll(); window.scrollTo(0, document.body.scrollHeight); }
        else status.textContent = r.error || "보내지 못했어요.";
      })
      .catch(function () { status.textContent = "보내지 못했어요. 인터넷 연결을 확인해 주세요."; });
  });

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stop(); else { poll(); start(); }
  });
  window.scrollTo(0, document.body.scrollHeight);
  start();
})();
