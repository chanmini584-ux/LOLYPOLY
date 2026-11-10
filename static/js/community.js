/* Lolypoly 커뮤니티 — 글쓰기 사진 미리보기·제거, 사진 크게 보기, 지우기 전 확인.
 * JS 가 꺼져 있어도 글쓰기·사진 올리기·사진 보기(새 탭)는 그대로 동작한다. */
(function () {
  "use strict";

  /* 1) 되돌릴 수 없는 버튼: 한 번 더 묻기 */
  document.addEventListener("submit", function (event) {
    var form = event.target;
    var msg = form.getAttribute && form.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) event.preventDefault();
  });

  /* 2) 사진 크게 보기: <dialog> 지원 브라우저에서만. 아니면 링크가 새 탭으로 연다 */
  var box = document.querySelector("[data-lightbox]");
  if (box && typeof box.showModal === "function") {
    var big = box.querySelector("[data-lightbox-img]");
    document.addEventListener("click", function (event) {
      var link = event.target.closest && event.target.closest("a[data-photo]");
      if (!link) return;
      event.preventDefault();
      big.src = link.href;
      box.showModal();
    });
    box.addEventListener("click", function (event) { if (event.target === box || event.target === big) box.close(); });
    box.addEventListener("close", function () { big.removeAttribute("src"); });
  }

  /* 3) 모집 글일 때만 '모집 상태' 보이기 */
  var catRow = document.querySelector("[data-category]");
  var recruit = document.querySelector("[data-recruit]");
  if (catRow && recruit) {
    catRow.addEventListener("change", function (event) {
      if (event.target.name === "category") recruit.hidden = event.target.value !== "recruit";
    });
  }

  /* 4) 사진 고르기: 여러 번 나눠 골라도 합쳐지고, 미리보기에서 하나씩 뺄 수 있다.
   *    고른 파일 목록은 DataTransfer 로 input.files 에 다시 넣는다(지원 안 하면 브라우저 기본 동작 그대로). */
  var input = document.getElementById("id_photos");
  var list = document.querySelector("[data-photo-preview]");
  var errorBox = document.querySelector("[data-photo-error]");
  if (!input || !list) return;
  var canRebuild = true;
  try { new DataTransfer(); } catch (e) { canRebuild = false; }
  if (!canRebuild) { document.documentElement.classList.add("no-js-photo"); return; }

  var maxCount = Number(input.getAttribute("data-max-count")) || 5;
  var maxBytes = (Number(input.getAttribute("data-max-bytes")) || 10) * 1024 * 1024;
  var existing = Number(input.getAttribute("data-existing")) || 0;
  var OK_TYPES = ["image/jpeg", "image/png", "image/webp"];
  var chosen = [];

  function keptExisting() {
    return existing - document.querySelectorAll('input[name="remove_photo"]:checked').length;
  }
  function showError(text) {
    if (!errorBox) return;
    errorBox.textContent = text || "";
    errorBox.hidden = !text;
  }
  function sync() {
    var dt = new DataTransfer();
    chosen.forEach(function (f) { dt.items.add(f); });
    input.files = dt.files;
  }
  function render() {
    Array.prototype.forEach.call(list.querySelectorAll("img"), function (img) { URL.revokeObjectURL(img.src); });
    list.innerHTML = "";
    chosen.forEach(function (file, index) {
      var li = document.createElement("li");
      var img = document.createElement("img");
      img.src = URL.createObjectURL(file);
      img.alt = "고른 사진 " + (index + 1);
      img.width = 96; img.height = 96;
      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "photo-preview__remove";
      remove.setAttribute("aria-label", "고른 사진 " + (index + 1) + " 빼기");
      remove.textContent = "×";
      remove.addEventListener("click", function () { chosen.splice(index, 1); sync(); render(); showError(""); });
      li.appendChild(img);
      li.appendChild(remove);
      if (index === 0 && keptExisting() <= 0) {
        var cover = document.createElement("span");
        cover.className = "photo-preview__cover";
        cover.textContent = "대표 사진";
        li.appendChild(cover);
      }
      list.appendChild(li);
    });
  }

  input.addEventListener("change", function () {
    var problems = [];
    Array.prototype.forEach.call(input.files, function (file) {
      if (chosen.some(function (f) { return f.name === file.name && f.size === file.size && f.lastModified === file.lastModified; })) return;
      if (OK_TYPES.indexOf(file.type) === -1) { problems.push("JPG·PNG·WebP 사진만 올릴 수 있어요."); return; }
      if (file.size > maxBytes) { problems.push("한 장은 " + Math.round(maxBytes / 1048576) + "MB까지 올릴 수 있어요."); return; }
      if (keptExisting() + chosen.length >= maxCount) { problems.push("사진은 글 하나에 " + maxCount + "장까지 올릴 수 있어요."); return; }
      chosen.push(file);
    });
    sync();
    render();
    showError(problems.length ? problems.filter(function (p, i) { return problems.indexOf(p) === i; }).join(" ") + " 맞는 사진만 담았어요." : "");
  });
  document.addEventListener("change", function (event) {
    if (event.target.name === "remove_photo") render();
  });

  /* 5) 등록 버튼 연타로 같은 글이 두 번 올라가지 않게 */
  var form = input.form;
  var submit = form && form.querySelector("[data-submit]");
  if (form && submit) {
    form.addEventListener("submit", function (event) {
      if (event.defaultPrevented) return;
      submit.disabled = true;
      submit.textContent = "올리는 중…";
    });
    window.addEventListener("pageshow", function () { submit.disabled = false; });
  }
})();
