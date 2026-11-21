"use strict";

// Page-independent presentation and chat. Financial answers use the same owned,
// privacy-aware /ask endpoint as Ask Tara; this widget cannot authorize payments.
window.ContextIQTaraWidget = (() => {
  const key = "contextiq.tara-position.v2";
  let geometry = null, panel = null, owner = null, rows = [], draft = "", pending = false;
  let requestNumber = 0, drag = null, suppressClick = false;
  try {
    const current = localStorage.getItem(key);
    const saved = JSON.parse(current || localStorage.getItem("contextiq.tara-position.v1") || "null");
    if (saved && !current) {
      saved.width = Math.min(saved.width, 320);
      if (Number.isFinite(saved.height)) saved.height = Math.min(saved.height, 420);
    }
    if (saved && [saved.x, saved.y, saved.width].every(Number.isFinite)
        && saved.x >= 0 && saved.x <= 1 && saved.y >= 0 && saved.y <= 1)
      geometry = saved;
  } catch { /* Geometry is optional; conversations never enter browser storage. */ }

  const clamp = (n, low, high) => Math.max(low, Math.min(n, Math.max(low, high)));
  function viewport() {
    const width = window.visualViewport?.width || window.innerWidth;
    const height = window.visualViewport?.height || window.innerHeight;
    return {width, height, bottom: width <= 700 && S.csrf ? 88 : 12};
  }
  function save() {
    try { localStorage.setItem(key, JSON.stringify(geometry)); } catch { /* Keep the current position in memory. */ }
  }
  function resetSession() {
    if (owner === S.csrf) return;
    owner = S.csrf; rows = []; draft = ""; pending = false; requestNumber++;
    renderChat();
  }
  function place(target = panel, tour = false) {
    if (!target || target.hidden) return;
    const view = viewport(), small = !target.hasAttribute("data-open");
    target.style.maxHeight = `${Math.max(100, view.height - view.bottom - 12)}px`;
    if (tour && !geometry) {
      const rect = target.getBoundingClientRect();
      target.style.top = `${clamp(rect.top, 12, view.height - rect.height - view.bottom)}px`;
      target.style.left = `${clamp(rect.left, 12, view.width - rect.width - 12)}px`;
      return;
    }
    const width = small ? 56 : clamp(geometry?.width || 320, Math.min(240, view.width - 24), view.width - 24);
    target.style.width = `${width}px`;
    if (!small && Number.isFinite(geometry?.height))
      target.style.height = `${clamp(geometry.height, Math.min(240, view.height - view.bottom - 12), view.height - view.bottom - 12)}px`;
    else target.style.removeProperty("height");
    const height = small ? 56 : target.getBoundingClientRect().height;
    const x = 12 + (geometry?.x ?? 1) * Math.max(0, view.width - width - 24);
    const y = 12 + (geometry?.y ?? 1) * Math.max(0, view.height - height - view.bottom - 12);
    Object.assign(target.style, {left: `${x}px`, top: `${y}px`, right: "auto", bottom: "auto"});
  }
  function setSize(width, height) {
    if (!Number.isFinite(width) || !Number.isFinite(height)) return;
    geometry = {...geometry, x: geometry?.x ?? 1, y: geometry?.y ?? 1, width, height};
    save(); place();
  }
  function compactSize(width, height) { return width < 230 || height < 200; }
  function collapseToBubble() {
    if (typeof guide !== "undefined") guide.minimize();
  }
  function renderChat() {
    if (!panel) return;
    const thread = panel.querySelector(".tara-inline-thread");
    if (!thread) return;
    thread.innerHTML = rows.map(row => messageHtml(row)).join("")
      + (pending ? '<p class="tara-wait" role="status">Checking your records…</p>' : "");
    const field = panel.querySelector("[data-tara-message]");
    if (field) field.value = draft;
    const send = panel.querySelector("[data-tara-send]");
    if (send) send.disabled = pending;
  }
  function captureFocus() {
    const field = panel?.querySelector("[data-tara-message]");
    return field && field === document.activeElement ? {start: field.selectionStart, end: field.selectionEnd} : null;
  }
  function restoreFocus(saved) {
    if (!saved) return;
    const field = panel?.querySelector("[data-tara-message]");
    field?.focus({preventScroll: true});
    field?.setSelectionRange(saved.start, saved.end);
  }
  async function ask(message) {
    resetSession();
    message = String(message || "").trim();
    if (!message || message.length > 2000 || pending) return;
    const session = owner, request = ++requestNumber;
    draft = ""; pending = true; renderChat();
    try {
      const answer = session ? await api("/ask", {message}) : {
        answer: "Start Meera’s private demo to ask about your records. Home shows your cash and priorities, Back office has invoices and clients, and Budget explains bills and savings. Payments always need your approval.",
        destination: "#/home", topic: "getting_started", evidence: [],
      };
      if (session !== S.csrf || request !== requestNumber) return;
      rows.push({question: message, ...answer});
      rows = rows.slice(-12);
    } catch (error) {
      if (session !== S.csrf || request !== requestNumber) return;
      rows.push({question: message, answer: `Unable to load an answer: ${error.message}. Please try again.`, destination: "#/transparency", evidence: []});
    } finally {
      if (session === S.csrf && request === requestNumber) { pending = false; renderChat(); place(panel, panel?.hasAttribute("data-tour")); }
    }
  }
  function mount(target, {open = false, tour = false} = {}) {
    panel = target; resetSession();
    if (open && !panel.querySelector(".tara-widget-chat")) {
      panel.insertAdjacentHTML("beforeend", `<section class="tara-widget-chat" aria-label="Ask Tara here">${S.csrf ? '<a class="tara-open-ask" href="#/ask">Open Ask Tara ↗</a>' : ""}<div class="tara-inline-thread" role="log" aria-label="Conversation with Tara" aria-live="polite"></div><form data-tara-chat><label for="tara-inline-question">Ask Tara without leaving this page</label><div class="tara-composer"><input id="tara-inline-question" data-tara-message name="message" maxlength="2000" required placeholder="Ask about your records…" autocomplete="off"><button type="submit" data-tara-send>Send ↗</button></div><p>${S.csrf ? 'Uses your AI privacy choice. <a href="#/transparency">AI &amp; Privacy</a>' : "Start a private demo for answers from your records."}</p></form></section><button class="tara-resize" type="button" data-tara-resize data-tara-corner="se" aria-label="Resize Tara: drag or use arrow keys" title="Drag to resize; shrink to minimize">↘</button>${["nw", "ne", "sw"].map(corner => `<button class="tara-resize tara-resize-${corner}" type="button" data-tara-resize data-tara-corner="${corner}" aria-label="Resize Tara from ${corner}" title="Drag to resize; shrink to minimize">⋱</button>`).join("")}`);
      const heading = panel.querySelector(".guide-top > span");
      if (heading) { heading.classList.add("tara-drag-handle"); heading.title = "Drag Tara to move it"; }
      renderChat();
    }
    place(panel, tour);
  }

  const widget = document.querySelector("#visual-guide");
  widget.addEventListener("submit", event => {
    if (!event.target.matches("[data-tara-chat]")) return;
    event.preventDefault(); event.stopPropagation();
    void ask(event.target.querySelector("[data-tara-message]").value);
  });
  widget.addEventListener("input", event => { if (event.target.matches("[data-tara-message]")) draft = event.target.value; });
  widget.addEventListener("click", event => {
    if (suppressClick) { suppressClick = false; event.preventDefault(); event.stopImmediatePropagation(); return; }
  }, true);
  widget.addEventListener("pointerdown", event => {
    if (event.button !== 0) return;
    const resize = event.target.closest("[data-tara-resize]");
    const bubble = event.target.closest(".guide-launch");
    if (!resize && !bubble && event.target.closest("button, input, select, textarea, a")) return;
    if (!resize && !event.target.closest(".guide-top, .guide-launch")) return;
    const rect = widget.getBoundingClientRect();
    drag = {id: event.pointerId, x: event.clientX, y: event.clientY, rect, resize: Boolean(resize), corner: resize?.dataset?.taraCorner || "se", moved: false, collapse: false};
    widget.setPointerCapture(event.pointerId);
  });
  widget.addEventListener("pointermove", event => {
    if (!drag || event.pointerId !== drag.id) return;
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) < 5 && !drag.moved) return;
    drag.moved = true; event.preventDefault();
    const view = viewport();
    if (drag.resize) {
      const fromLeft = drag.corner.includes("w"), fromTop = drag.corner.includes("n");
      const width = drag.rect.width + (fromLeft ? -dx : dx), height = drag.rect.height + (fromTop ? -dy : dy);
      drag.collapse = compactSize(width, height);
      widget.toggleAttribute("data-shrink-to-icon", drag.collapse);
      if (!drag.collapse) {
        const boundedWidth = clamp(width, Math.min(240, view.width - 24), view.width - 24);
        const boundedHeight = clamp(height, Math.min(240, view.height - view.bottom - 12), view.height - view.bottom - 12);
        const left = drag.rect.left + (fromLeft ? drag.rect.width - boundedWidth : 0);
        const top = drag.rect.top + (fromTop ? drag.rect.height - boundedHeight : 0);
        geometry = {width: boundedWidth, height: boundedHeight,
          x: clamp((left - 12) / Math.max(1, view.width - boundedWidth - 24), 0, 1),
          y: clamp((top - 12) / Math.max(1, view.height - boundedHeight - view.bottom - 12), 0, 1)};
        save(); place();
      }
    }
    else {
      const maxX = Math.max(1, view.width - drag.rect.width - 24), maxY = Math.max(1, view.height - drag.rect.height - view.bottom - 12);
      geometry = {...geometry, width: geometry?.width || (widget.hasAttribute("data-open") ? drag.rect.width : 320),
        x: clamp((drag.rect.left + dx - 12) / maxX, 0, 1), y: clamp((drag.rect.top + dy - 12) / maxY, 0, 1)};
      place();
    }
  });
  const finishDrag = event => {
    if (!drag || event.pointerId !== drag.id) return;
    const collapse = drag.resize && drag.collapse;
    widget.removeAttribute("data-shrink-to-icon");
    if (drag.moved) { save(); suppressClick = true; window.setTimeout(() => { suppressClick = false; }, 0); }
    drag = null;
    if (collapse) collapseToBubble();
  };
  widget.addEventListener("pointerup", finishDrag);
  widget.addEventListener("pointercancel", event => { if (drag) drag.collapse = false; finishDrag(event); suppressClick = false; });
  widget.addEventListener("keydown", event => {
    if (!event.target.matches("[data-tara-resize]")) return;
    const delta = {ArrowLeft: [-20, 0], ArrowRight: [20, 0], ArrowUp: [0, -20], ArrowDown: [0, 20]}[event.key];
    if (!delta) return;
    event.preventDefault(); const rect = widget.getBoundingClientRect();
    const width = rect.width + delta[0], height = rect.height + delta[1];
    if (compactSize(width, height)) collapseToBubble();
    else setSize(width, height);
  });
  window.addEventListener("resize", () => place(panel, panel?.hasAttribute("data-tour")));
  window.visualViewport?.addEventListener("resize", () => place(panel, panel?.hasAttribute("data-tour")));
  return {mount, place, resetSession, setSize, ask, captureFocus, restoreFocus};
})();
