"use strict";

// The guide reads the same authorized page data as the app. Its only actions
// are presentation controls and focusing an existing element.
const guide = (() => {
  const storageKey = "contextiq.visual-guide.paused";
  let paused = false;
  try {
    paused = localStorage.getItem(storageKey) === "yes";
  } catch {
    /* Browser storage can be disabled. */
  }

  let current = null;
  let highlighted = null;
  let openTip = null;
  let openAlert = null;
  const nextTips = new Map();
  const dismissed = new Set();
  const seenAlerts = new Set();
  const alertStorageKey = "contextiq.urgent-reminders.v1";
  let storedAlerts = {};
  try {
    const saved = JSON.parse(localStorage.getItem(alertStorageKey) || "{}");
    if (saved && typeof saved === "object" && !Array.isArray(saved))
      storedAlerts = saved;
  } catch {
    /* Keep deduplication in memory if browser storage is unavailable. */
  }

  function alreadyShown(id) {
    return seenAlerts.has(id) || Boolean(storedAlerts[id]);
  }

  function rememberAlert(id) {
    seenAlerts.add(id);
    const oldest = Date.now() - 2 * 86400000;
    storedAlerts = Object.fromEntries(
      Object.entries(storedAlerts)
        .filter(([, shownAt]) => shownAt > oldest)
        .slice(-47),
    );
    storedAlerts[id] = Date.now();
    try {
      localStorage.setItem(alertStorageKey, JSON.stringify(storedAlerts));
    } catch {
      /* The open tab still shows each alert once. */
    }
  }

  function cue(id, selector, title, body, values = {}) {
    const text = t(body).replace(
      /\{(\w+)\}/g,
      (match, name) => values[name] ?? match,
    );
    return { id, selector, title: t(title), body: text };
  }

  function paymentCue(invoice) {
    const id = invoice.id;
    if (invoice.status === "provider_checkout") {
      return cue(
        id + ":provider",
        '[data-action="provider-check"]',
        "Payment verification",
        "Check the existing order before you consider another payment.",
      );
    }
    if (invoice.status === "paid") {
      return cue(
        id + ":paid",
        'a[href="#/purchases/after"]',
        "Payment confirmed",
        "Open your purchases to follow delivery and find the payment record.",
      );
    }
    if (invoice.status === "authorized") {
      return cue(
        id + ":authorized",
        '[data-action="reconcile"]',
        "Check the original payment",
        "Check the existing order before you consider another payment.",
      );
    }
    if (invoice.status !== "open") return null;
    if (new Date(invoice.expires_at).getTime() <= Date.now()) {
      return cue(
        id + ":expired",
        '[data-action="regenerate"]',
        "This invoice has expired",
        "Generate a new invoice and review its details before paying.",
      );
    }
    if (invoice.affordability.alternative) {
      return cue(
        id + ":alternative",
        '[data-action="alternative"]',
        "This purchase exceeds your flexible funds.",
        "You’re {amount} short after your commitments. Compare the lower-priced option.",
        { amount: money(-invoice.affordability.remaining_minor) },
      );
    }
    if (invoice.affordability.remaining_minor < 0) {
      return cue(
        id + ":shortfall",
        "a.back",
        "This purchase exceeds your flexible funds.",
        "You’re {amount} short after your commitments. Go back to review your purchase options.",
        { amount: money(-invoice.affordability.remaining_minor) },
      );
    }
    return cue(
      id + ":review",
      '#authorize-form input[name="authorized"]',
      "Review and authorize",
      "Check the items, recipient and total of {amount}. Authorize only if the details match.",
      { amount: money(invoice.total_minor) },
    );
  }

  function purchaseCue(item) {
    const briefcase = 'a[href^="#/activity/briefcase/"]';
    if (item.request) {
      return cue(
        `${item.id}:${item.request}`,
        briefcase,
        "Complete briefcase",
        "Follow your request and its supporting evidence in the purchase briefcase.",
      );
    }
    if (!item.delivered_at && item.refunded_quantity < item.quantity) {
      return cue(
        item.id + ":tracking",
        briefcase,
        "Delivery",
        "Check the purchase timeline for shipment updates. Return and replacement windows start at delivery.",
      );
    }
    if (
      item.replacement_days !== null &&
      item.replacement_days > 0 &&
      item.refunded_quantity < item.quantity
    ) {
      return cue(
        item.id + ":replacement",
        '[data-action="item-action"][data-id="replacement"]',
        "Replacement window",
        "If there’s a defect, you have {days} days left to request a replacement.",
        { days: item.replacement_days },
      );
    }
    return cue(
      item.id + ":policy",
      briefcase,
      "Complete briefcase",
      "Open the purchase briefcase for the original terms and recorded updates.",
    );
  }

  function pageCue() {
    if (
      !S.csrf ||
      !S.profile.onboarded ||
      !$("#main") ||
      $("#main .error-page")
    )
      return null;
    const [page, section] = S.route;
    if (page === "home" && S.dashboard?.focus) {
      const record = S.dashboard.focus;
      const timing = reminderTiming(record, S.dashboard.task_date);
      if (timing?.tone !== "urgent") return null;
      const focus = observationText(record);
      return {
        ...cue(
          `${S.dashboard.task_date}:${record.id}`,
          "#daily-checklist-body:not([hidden]) [data-next-task] .daily-link, .daily-compact:not([hidden]) .daily-link",
          focus.title,
          record.kind === "payment"
            ? "Open the payment issue to see what has been verified so far."
            : focus.description,
        ),
        alert: timing,
      };
    }
    if (page === "invoice" && S.invoice) return paymentCue(S.invoice);
    if (page === "purchases" && section === "item" && S.item)
      return purchaseCue(S.item);
    if (page === "purchases" && section === "after") {
      return cue(
        "purchases-after",
        '#main a[href^="#/purchases/item/"]',
        "After Payment",
        "Open a purchase to see delivery, policy dates and the complete briefcase.",
      );
    }
    if (page === "activity" && section === "issues" && S.route[2]) {
      return cue(
        `issue:${S.route[2]}`,
        '#main a[href^="#/activity/briefcase/"]',
        "Payment verification",
        "Open the original briefcase to see the provider evidence and payment timeline.",
      );
    }
    if (page === "scan") {
      return cue(
        "scan",
        "#token",
        "Scan & Pay",
        "Paste your QR text here to verify its details before any payment.",
      );
    }
    if (page === "budget" && ["bills", "business-bills"].includes(section)) {
      return cue(
        `bill:${S.route[2] ?? "open"}`,
        '[data-action="bill-pay"]',
        "Review bill",
        "Check the amount and due date. Record a payment here only after you’ve paid it elsewhere.",
      );
    }
    return null;
  }

  async function refreshHomeFocus(force = false) {
    if (
      document.hidden ||
      !navigator.onLine ||
      (!force && S.busy) ||
      S.route[0] !== "home" ||
      !$(".daily-checklist")
    )
      return;
    const renderId = S.renderId;
    try {
      const data = await api("/dashboard");
      const panel = $(".daily-checklist");
      if (S.renderId !== renderId || S.route[0] !== "home" || !panel) return;
      const previous = S.dashboard;
      const listChanged = data.task_date !== previous.task_date ||
        JSON.stringify(data.suggestions) !== JSON.stringify(previous.suggestions);
      const figuresChanged = data.workspace !== previous.workspace ||
        data.flexible_minor !== previous.flexible_minor ||
        JSON.stringify(data.finance) !== JSON.stringify(previous.finance);
      S.dashboard = data;
      S.profile = data.profile;
      const figures = $("[data-home-figures]");
      if (figuresChanged && figures) {
        figures.outerHTML = homeOverview(data);
        drawChart("balance-chart", data.finance.chart);
      }
      if (!listChanged) return;
      const checkedId = document.activeElement?.dataset?.dailyTask;
      const viewControl = document.activeElement?.closest(
        ".daily-toggle, .daily-compact .daily-link",
      );
      const coverageOpen = $(".agent-coverage", panel)?.open;
      const advanced = data.focus?.id !== previous.focus?.id;
      panel.innerHTML = dailyChecklist(data);
      if (advanced)
        $("[data-next-task]", panel)?.setAttribute("data-advanced", "");
      if (coverageOpen) $(".agent-coverage", panel).open = true;
      if (viewControl)
        $(
          viewControl.matches(".daily-toggle")
            ? ".daily-toggle"
            : ".daily-compact .daily-link",
          panel,
        )?.focus({ preventScroll: true });
      if (checkedId)
        panel
          .querySelector(`[data-daily-task="${CSS.escape(checkedId)}"]`)
          ?.focus({ preventScroll: true });
      update();
    } catch (error) {
      if (force) throw error;
    }
  }

  function removeHighlight() {
    highlighted?.classList.remove("guide-target");
    highlighted = null;
  }

  function draw() {
    const panel = $("#visual-guide");
    removeHighlight();
    const target = current && $(current.selector);
    if (
      target &&
      current.alert &&
      !paused &&
      !$("#dialog").open &&
      !document.hidden &&
      !alreadyShown(current.id)
    ) {
      openAlert = current.id;
      rememberAlert(current.id);
    }
    panel.hidden =
      !target ||
      $("#dialog").open ||
      (current.alert && (paused || openAlert !== current.id));
    panel.toggleAttribute(
      "data-urgent-alert",
      Boolean(current?.alert && !panel.hidden),
    );
    if (panel.hidden) {
      panel.removeAttribute("data-open");
      panel.textContent = "";
      return;
    }

    const open =
      !paused &&
      !dismissed.has(current.id) &&
      (current.alert || openTip === current.id);
    panel.toggleAttribute("data-open", open);
    if (!open) {
      panel.innerHTML = `<button type="button" class="guide-launch" data-guide="open"><span aria-hidden="true">✦</span> ${esc(t("Tara, your visual guide"))}</button>`;
      return;
    }

    highlighted = target.closest(".form-check") || target;
    highlighted.classList.add("guide-target");
    panel.setAttribute("aria-label", t("Tara, your visual guide"));
    panel.innerHTML = `<div class="guide-top"><span><span class="guide-mark" aria-hidden="true">${current.alert ? "◴" : "✦"}</span> ${esc(current.alert ? `Tara · ${current.alert.label}` : t("Tara, your visual guide"))}</span><button type="button" class="guide-close" data-guide="dismiss" aria-label="${esc(t("Dismiss this tip"))}">×</button></div><div class="guide-copy" role="status" aria-live="polite"><h2>${esc(current.title)}</h2><p>${esc(current.body)}</p></div><div class="guide-controls"><button type="button" class="btn green small" data-guide="show">${esc(t("Show me"))} <span aria-hidden="true">↗</span></button><button type="button" class="guide-pause" data-guide="pause">${esc(t("Pause tips"))}</button></div>`;
  }

  async function updateNextTip() {
    const task = S.route[0] === "home" && S.dashboard?.focus;
    const tip = $("[data-tara-next-tip]");
    if (!task || !tip) return;
    if (paused) {
      tip.hidden = true;
      return;
    }
    const timing = reminderTiming(task, S.dashboard.task_date)?.tone;
    const urgency = ["urgent", "soon"].includes(timing) ? timing : "normal";
    const key = `${task.kind}:${urgency}`;
    if (!nextTips.has(key)) nextTips.set(key, api(`/guide/tip?kind=${task.kind}&urgency=${urgency}`));
    try {
      const result = await nextTips.get(key);
      if (!paused && tip.isConnected && S.dashboard?.focus?.id === task.id) {
        tip.textContent = t(result.text);
        tip.hidden = false;
      }
    } catch {
      nextTips.delete(key);
    }
  }

  function update() {
    current = pageCue();
    draw();
    void updateNextTip();
  }

  function clear() {
    current = null;
    openTip = null;
    openAlert = null;
    draw();
  }

  $("#visual-guide").addEventListener("click", (event) => {
    const command = event.target.closest("[data-guide]")?.dataset.guide;
    if (!command || !current) return;
    if (command === "show") {
      const target = $(current.selector);
      if (!target) return;
      target.scrollIntoView({
        block: "center",
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "instant"
          : "smooth",
      });
      target.focus({ preventScroll: true });
      if (current.alert) {
        openAlert = null;
        draw();
      }
      return;
    }
    if (command === "dismiss") dismissed.add(current.id);
    if (command === "pause") paused = true;
    if (current.alert) openAlert = null;
    if (command === "open") {
      paused = false;
      openTip = current.id;
      dismissed.delete(current.id);
    }
    try {
      localStorage.setItem(storageKey, paused ? "yes" : "no");
    } catch {
      /* The in-memory preference still works. */
    }
    draw();
    $(
      command === "open" ? '[data-guide="show"]' : '[data-guide="open"]',
    )?.focus();
    void updateNextTip();
  });

  $("#dialog").addEventListener("close", update);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && current?.alert) draw();
  });
  window.setInterval(async () => {
    await refreshHomeFocus();
    const [page, section, id] = S.route;
    if (document.hidden || S.busy || $("#dialog").open || page !== "budget") return;
    try {
      if (section === "allocation") {
        const data = await api("/dashboard");
        if (JSON.stringify(data.allocation) !== JSON.stringify(S.dashboard?.allocation)) queueWorkspaceRefresh();
      }
      if (section === "goals") {
        const plans = (await api("/plans")).filter((plan) => plan.kind === "goal" && (!id || plan.id === id));
        if (JSON.stringify(plans) !== JSON.stringify(S.plans)) queueWorkspaceRefresh();
      }
    } catch {
      // The plan remains visible while its data source is temporarily unavailable.
    }
  }, 60_000);
  window.setInterval(async () => {
    const invoice = S.invoice;
    const activeInvoice = () => S.route[0] === "invoice" && S.route[1] === invoice?.id;
    if (document.hidden || S.busy || !activeInvoice() || invoice?.status !== "authorized") return;
    try {
      const updated = await api(`/invoices/${invoice.id}`);
      if (updated.status === "paid" && activeInvoice() && !S.busy) {
        publishWorkspaceUpdate();
        await render();
      }
    } catch {
      // A stale or disconnected session can still retry from the invoice page.
    }
  }, 15_000);

  return { update, clear, refreshHomeFocus };
})();
