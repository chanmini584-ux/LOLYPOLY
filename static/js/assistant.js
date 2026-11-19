/* 롤리폴리 안내(D-073) — 식단 화면의 작은 질문 칸.
 * - 같은 출처 POST(/assistant/ask/) + CSRF 헤더. 지금 질문 하나만 보낸다(대화 기록·개인 정보는 보내지 않음).
 * - 보내는 중에는 버튼·입력을 잠가 중복 전송을 막는다. 대화는 화면에만 보이고 저장하지 않는다(새로고침하면 사라짐).
 * - 다섯 상태: answered / partial / insufficient_evidence / clarification_needed / unavailable.
 *   장애(연결 실패·429·시간 초과·unavailable)는 대화 기록이 아니라 상태 줄에 보여 주고, 입력을 되살려 다시 시도할 수 있게 한다.
 * - 답과 인용은 textContent 로만 넣는다. 링크는 http(s) 주소만 만든다.
 */
(function () {
  "use strict";
  const root = document.querySelector("[data-assistant]");
  if (!root) return;

  const endpoint = root.dataset.endpoint;
  const form = root.querySelector("[data-assistant-form]");
  const input = root.querySelector("[data-assistant-input]");
  const send = root.querySelector("[data-assistant-send]");
  const log = root.querySelector("[data-assistant-log]");
  const statusEl = root.querySelector("[data-assistant-status]");
  const retry = root.querySelector("[data-assistant-retry]");
  const clear = root.querySelector("[data-assistant-clear]");
  const examples = root.querySelectorAll("[data-assistant-example]");
  const BROWSER_TIMEOUT_MS = 75000;   // 서버(앱→엔진 60초)보다 조금 길게
  const MAX_ITEMS = 12;               // 화면에 남기는 말풍선 수
  const defaultPlaceholder = input.placeholder;
  let busy = false;
  let lastQuestion = "";
  let pendingClarify = "";            // 되묻기를 받은 원래 질문(다음 입력과 합쳐 한 문장으로 보낸다)

  function csrfToken() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    const field = form.querySelector("input[name=csrfmiddlewaretoken]");
    return field ? field.value : "";
  }

  function setBusy(on) {
    busy = on;
    send.disabled = on;
    input.readOnly = on;
    examples.forEach((b) => { b.disabled = on; });
    root.setAttribute("aria-busy", on ? "true" : "false");
  }

  function setStatus(text, tone) {
    statusEl.textContent = text || "";
    statusEl.className = "assistant__status" + (tone ? ` is-${tone}` : "");
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function safeUrl(url) {
    return typeof url === "string" && /^https?:\/\//.test(url) ? url : "";
  }

  function trim() {
    while (log.children.length > MAX_ITEMS) log.removeChild(log.firstChild);
    clear.hidden = log.children.length === 0;
  }

  function addUser(text) {
    const li = el("li", "assistant__msg assistant__msg--user");
    li.appendChild(el("span", "visually-hidden", "나: "));
    li.appendChild(el("p", "", text));
    log.appendChild(li);
    trim();
    return li;
  }

  const LABELS = {
    answered: "",
    partial: "일부만 확인했어요",
    insufficient_evidence: "자료에서 찾지 못했어요",
    clarification_needed: "조금 더 알려 주세요",
  };

  function renderCitations(cites) {
    const ol = el("ol", "assistant__cites");
    cites.forEach((c, i) => {
      const li = el("li", "assistant__cite");
      const head = el("p", "assistant__cite-head");
      head.appendChild(el("span", "assistant__cite-no", `[${i + 1}] `));
      const url = safeUrl(c.url);
      if (url) {
        const a = el("a", "", c.title || url);
        a.href = url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        head.appendChild(a);
      } else {
        head.appendChild(el("span", "", c.title || "자료"));
      }
      head.appendChild(el("span", "assistant__badge", c.source_label || "자료"));
      li.appendChild(head);
      const meta = [c.locator, c.as_of, c.note].filter(Boolean).join(" · ");
      if (meta) li.appendChild(el("p", "assistant__cite-meta", meta));
      if (c.quote) li.appendChild(el("blockquote", "assistant__quote", c.quote));
      ol.appendChild(li);
    });
    return ol;
  }

  function addAnswer(data) {
    const li = el("li", `assistant__msg assistant__msg--bot is-${data.status}`);
    li.appendChild(el("span", "visually-hidden", "안내: "));
    const label = LABELS[data.status];
    if (label) li.appendChild(el("p", "assistant__label", label));
    const lines = String(data.answer || "").split("\n").filter(Boolean);
    lines.forEach((line) => {
      const gap = line.startsWith("[일부는 확인하지 못했어요]");
      li.appendChild(el("p", gap ? "assistant__gap" : "assistant__line", gap ? line.replace("[일부는 확인하지 못했어요]", "확인 못 한 부분:") : line));
    });
    if (data.citations && data.citations.length) li.appendChild(renderCitations(data.citations));
    log.appendChild(li);
    trim();
    li.scrollIntoView({ block: "nearest" });
  }

  function fail(message, question, bubble) {
    if (bubble && bubble.parentNode) bubble.parentNode.removeChild(bubble);   // 실패한 질문은 기록에서 빼고 입력으로 되돌린다
    trim();
    setStatus(message, "error");
    input.value = question;          // 입력 복구
    retry.hidden = false;
    input.focus();
  }

  async function ask(rawQuestion) {
    const typed = String(rawQuestion || "").trim();
    if (!typed || busy) return;
    // 되묻기에 대한 짧은 답(예: "점심")만 원래 질문과 합친다. 새 질문을 쓰면 새 질문으로 보낸다.
    const shortReply = !/[?？]/.test(typed) && typed.split(/\s+/).length <= 4;
    const question = (pendingClarify && shortReply ? `${pendingClarify} ${typed}` : typed).slice(0, 500);
    lastQuestion = question;
    retry.hidden = true;
    const bubble = addUser(typed);
    input.value = "";
    setBusy(true);
    setStatus("답을 찾는 중이에요…");
    const started = Date.now();
    const tick = window.setInterval(() => {
      const s = Math.round((Date.now() - started) / 1000);
      if (s >= 5) setStatus(`답을 찾는 중이에요… ${s}초 (문장 답변은 1분 가까이 걸릴 수 있어요)`);
    }, 1000);
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => ctrl.abort(), BROWSER_TIMEOUT_MS);
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
        body: JSON.stringify({ question }),
        signal: ctrl.signal,
      });
      let data = null;
      try { data = await res.json(); } catch (e) { data = null; }
      if (!res.ok) {
        const msg = (data && data.message) || (res.status === 403 ? "화면이 오래돼서 보내지 못했어요. 새로고침한 뒤 다시 시도해 주세요." : "잠시 뒤 다시 시도해 주세요.");
        fail(msg, typed, bubble);
        return;
      }
      if (!data || data.status === "unavailable") {
        fail("안내 서버에 잠시 문제가 있어요. 공식 식단 페이지를 확인하거나 다시 시도해 주세요.", typed, bubble);
        return;
      }
      pendingClarify = data.status === "clarification_needed" ? question : "";
      input.placeholder = pendingClarify ? "위 질문에 대한 답을 적어 주세요 (예: 점심)" : defaultPlaceholder;
      addAnswer(data);
      setStatus("");
      if (pendingClarify) input.focus();
    } catch (e) {
      fail(e && e.name === "AbortError" ? "답변이 너무 오래 걸려서 멈췄어요. 다시 시도해 주세요." : "연결이 끊겼어요. 인터넷 연결을 확인하고 다시 시도해 주세요.", typed, bubble);
    } finally {
      window.clearInterval(tick);
      window.clearTimeout(timer);
      setBusy(false);
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    ask(input.value);
  });
  examples.forEach((b) => b.addEventListener("click", () => { pendingClarify = ""; ask(b.textContent); }));
  retry.addEventListener("click", () => {
    // 되묻기에 답하던 중이었다면 합친 질문(lastQuestion)을 그대로 다시 보낸다
    const q = pendingClarify ? lastQuestion : (input.value || lastQuestion);
    pendingClarify = "";
    ask(q);
  });
  clear.addEventListener("click", () => {
    log.textContent = "";
    pendingClarify = "";
    input.placeholder = defaultPlaceholder;
    setStatus("");
    retry.hidden = true;
    trim();
  });
})();
