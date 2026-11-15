"use strict";
// Pages are plain HTML templates; every user/provider value passes through esc().
const S = {
  csrf: "",
  profile: { language: "en" },
  route: [],
  dashboard: null,
  invoice: null,
  persona: "student",
  step: 0,
  busy: false,
  stream: null,
};
const $ = (selector, root = document) => root.querySelector(selector);
const esc = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll(String.fromCharCode(34), "&quot;")
    .replaceAll("'", "&#39;");
const t = (text) => window.CIQ_LOCALES[S.profile.language]?.[text] || text;
const money = (minor) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
    minimumFractionDigits: minor % 100 ? 2 : 0,
  }).format((minor || 0) / 100);
const date = (value) =>
  new Intl.DateTimeFormat(
    { en: "en-IN", hi: "hi-IN", kn: "kn-IN" }[S.profile.language] || "en-IN",
    { day: "numeric", month: "short", year: "numeric" },
  ).format(new Date(value));
const status = (value) =>
  `<span class="status ${["open", "checking", "authorized", "draft"].includes(value) ? "warn" : ""}">${esc(t(value).replaceAll("_", " "))}</span>`;
const button = (label, action, id = "", kind = "") =>
  `<button class="btn ${kind}" data-action="${action}" data-id="${esc(id)}">${esc(t(label))}</button>`;
const link = (label, path, kind = "") =>
  `<a class="btn ${kind}" href="#/${path}">${esc(t(label))}</a>`;
const kv = (label, value) =>
  `<div class="detail-kv"><span>${esc(t(label))}</span><strong>${value}</strong></div>`;
const field = (label, name, value = "", type = "text", extra = "") =>
  `<div class="form-field"><label for="${name}">${esc(t(label))}</label><input id="${name}" name="${name}" type="${type}" value="${esc(value)}" ${extra}></div>`;
const selectField = (label, name, options, value) =>
  `<div class="form-field"><label for="${name}">${esc(t(label))}</label><select id="${name}" name="${name}">${options.map(([key, label]) => `<option value="${esc(key)}" ${key === value ? "selected" : ""}>${esc(t(label))}</option>`).join("")}</select></div>`;
const check = (label, name, checked = false) =>
  `<label class="form-check"><input type="checkbox" name="${name}" ${checked ? "checked" : ""}><span>${esc(t(label))}</span></label>`;
const head = (title, subtitle = "", action = "") =>
  `<div class="page-head"><div><h1>${esc(t(title))}</h1>${subtitle ? `<p>${esc(t(subtitle))}</p>` : ""}</div>${action}</div>`;
const back = (path, label = "Back") =>
  `<a class="back" href="#/${path}">← ${esc(t(label))}</a>`;
const empty = (path = "store", label = "Browse BrightMart") =>
  `<div class="empty"><h2>${esc(t("No records yet"))}</h2><p>${esc(t("Your records will appear here."))}</p>${link(label, path, "green")}</div>`;
const formFooter = (label) =>
  `<div class="actions"><button type="submit" class="btn green">${esc(t(label))}</button>${button("Cancel", "close", "", "white")}</div>`;
const occupations = [
  ["student", "Student"],
  ["salaried", "Salaried employee"],
  ["shopkeeper", "Shopkeeper"],
  ["freelancer", "Freelancer"],
  ["homemaker", "Homemaker"],
  ["investor", "Investor"],
  ["other", "Other"],
];
const configurations = [
  ["personal", "Personal finances only"],
  ["business", "Business finances only"],
  ["separate", "Separate personal & business"],
  ["unified", "One account for everything"],
];

async function api(path, body, method) {
  if (!navigator.onLine)
    throw new Error(t("You are offline. Reconnect to load current records."));
  const response = await fetch(`/api/v2${path}`, {
    method: method || (body === undefined ? "GET" : "POST"),
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": S.csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    const detail =
      typeof data.detail === "string"
        ? data.detail
        : data.detail?.map((e) => e.msg).join(", ");
    const error = new Error(detail || t("Something went wrong"));
    error.status = response.status;
    throw error;
  }
  return data;
}
function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.style.display = "block";
  clearTimeout(S.toastTimer);
  S.toastTimer = setTimeout(() => (el.style.display = "none"), 4500);
}
function modal(html) {
  stopCamera();
  $("#dialog-content").innerHTML = html;
  if (!$("#dialog").open) $("#dialog").showModal();
  guide.update();
}
function closeModal() {
  stopCamera();
  $("#dialog").close();
}
function navigate(path) {
  if (location.hash === `#/${path}`) render();
  else location.hash = `#/${path}`;
}
function stopCamera() {
  if (S.stream) S.stream.getTracks().forEach((track) => track.stop());
  S.stream = null;
}
function phaseLabel(route) {
  return (
    {
      home: "Home",
      purchases: "Purchases",
      budget: "Budget",
      activity: "Activity",
      ask: "Ask",
      preferences: "Preferences",
      store: "Store",
      watch: "Cart Intelligence",
      cart: "Cart",
      invoice: "Invoice",
      qr: "Create Dynamic QR",
      scan: "Scan & Pay",
      merchant: "Merchant desk",
      notices: "Notices",
      notifications: "Notifications",
    }[route] || "Home"
  );
}

function welcome() {
  $("#app").innerHTML =
    `<div class="welcome"><section class="welcome-art"><div class="brand">ContextIQ<b>.</b></div><div><h1>Your money.<br><span>Understood.</span></h1><p>A little more clarity. A little more control.<br>For the everyday decisions that matter.</p><div class="orb" aria-hidden="true">↗</div></div><div class="eyebrow">Built around your life</div></section><section class="welcome-form"><div class="welcome-content"><span class="demo-tag">PRIVATE DEMO</span><h2>Make yourself at home.</h2><p>Explore a connected financial workspace with fictional records. Choose a starting point.</p>${[
      ["student", "P", "Priya", "Student · everyday budgeting"],
      ["salaried", "A", "Arjun", "Salaried · bills and future plans"],
      [
        "shopkeeper",
        "K",
        "Kavya",
        "Kirana shop owner · personal and shop finances",
      ],
    ]
      .map(
        ([id, initial, name, description]) =>
          `<button class="persona ${S.persona === id ? "selected" : ""}" data-action="persona" data-id="${id}"><span class="avatar">${initial}</span><div><h3>${name}</h3><p>${description}</p></div><span class="arrow">${S.persona === id ? "✓" : ""}</span></button>`,
      )
      .join(
        "",
      )}<div class="spacer"></div>${button("Try the demo", "start", "", "green")}<p class="field-hint" style="margin-top:18px">Fictional data. Simulated payments. Your workspace is private to this browser session.</p></div></section></div>`;
}
function onboarding() {
  const titles = [
    "Which language feels like home?",
    "Tell us a little about yourself",
    "How do you manage your money?",
    "What matters most to you?",
  ];
  let content = "";
  if (S.step === 0)
    content = `<div class="choices">${[
      ["en", "English"],
      ["hi", "हिन्दी"],
      ["kn", "ಕನ್ನಡ"],
    ]
      .map(
        ([code, name]) =>
          `<button class="choice ${S.profile.language === code ? "selected" : ""}" data-action="language" data-id="${code}">${name}<span style="float:right">${S.profile.language === code ? "✓" : ""}</span></button>`,
      )
      .join("")}</div>`;
  if (S.step === 1)
    content =
      field("What should we call you?", "name", S.profile.name) +
      selectField(
        "Occupation",
        "occupation",
        occupations,
        S.profile.occupation,
      ) +
      field(
        "Income frequency (optional)",
        "income_frequency",
        S.profile.income_frequency || "",
      );
  if (S.step === 2)
    content = `<div class="choices">${configurations.map(([key, label]) => `<button class="choice ${S.profile.configuration === key ? "selected" : ""}" data-action="configuration" data-id="${key}">${esc(t(label))}</button>`).join("")}</div>${["business", "separate", "unified"].includes(S.profile.configuration) ? `<div class="spacer"></div>${field("Business type", "business_type", S.profile.business_type || "")}` : ""}`;
  if (S.step === 3)
    content = `<div class="form-grid">${[
      ["budget", "Budget"],
      ["purchases", "Purchases"],
      ["goals", "Future Purchases"],
      ["emi", "EMI Commitments"],
      ["business", "Business"],
    ]
      .map(([key, label]) =>
        check(
          label,
          `feature-${key}`,
          (S.profile.features || []).includes(key),
        ),
      )
      .join(
        "",
      )}</div><div class="spacer"></div>${check("Automatically choose a workspace using activity and working hours", "context_consent", S.profile.context_consent)}${check("Voice assistance", "voice_enabled", S.profile.voice_enabled)}${check("Learn from my confirmed preferences", "learning_enabled", S.profile.learning_enabled)}`;
  $("#app").innerHTML =
    `<section class="onboard"><div class="brand">ContextIQ<b>.</b></div><div class="steps">${[0, 1, 2, 3].map((n) => `<span class="${n <= S.step ? "done" : ""}"></span>`).join("")}</div><h1>${esc(t(titles[S.step]))}</h1><form id="onboarding-form">${content}<div class="onboard-actions">${S.step ? button("Back", "onboard-back", "", "white") : "<span></span>"}<button type="submit" class="btn green">${esc(t(S.step === 3 ? "Start my workspace" : "Continue"))} →</button></div></form><p class="field-hint" style="margin-top:24px">${esc(t("Fictional data. Simulated payments."))}</p></section>`;
  document.documentElement.lang = S.profile.language;
}
function shell() {
  const primary = S.route[0] === "watch" ? "purchases" : S.route[0] || "home",
    nav = [
      ["home", "⌂", "Home"],
      ["purchases", "▣", "Purchases"],
      ["budget", "▤", "Budget"],
      ["activity", "↗", "Activity"],
      ["ask", "✦", "Ask"],
    ];
  const navHtml = nav
    .map(
      ([path, icon, label]) =>
        `<a href="#/${path}" class="${primary === path ? "active" : ""}"><span class="nav-icon" aria-hidden="true">${icon}</span><span>${esc(t(label))}</span></a>`,
    )
    .join("");
  $("#app").innerHTML =
    `<aside class="sidebar"><a class="brand" href="#/home">ContextIQ<b>.</b></a><nav class="nav" aria-label="Main navigation">${navHtml}</nav><div class="sidebar-bottom"><nav class="nav"><a class="${primary === "preferences" ? "active" : ""}" href="#/preferences"><span class="nav-icon">⚙</span>${esc(t("Preferences"))}</a></nav><p class="sidebar-note"><i></i>${esc(t("Your private financial demo"))}<br>${esc(t("No money moves in this demo"))}</p></div></aside><div class="shell"><header class="topbar"><div class="crumb"><span class="crumb-prefix">${esc(t("Your money, understood."))}</span><strong>${esc(t(phaseLabel(primary)))}</strong></div><div class="top-actions">${
      S.profile.configuration === "separate"
        ? `<div class="workspace"><select aria-label="Financial workspace" id="workspace-select">${[
            ["auto", "Auto"],
            ["personal", "Personal"],
            ["business", "Business"],
          ]
            .map(
              ([key, label]) =>
                `<option value="${key}" ${S.profile.override === key ? "selected" : ""}>${esc(t(label))}</option>`,
            )
            .join("")}</select></div>`
        : ""
    }<span class="demo-tag">${esc(t("Demo"))}</span><a class="header-button" href="#/notices" aria-label="${esc(t("Notices"))}">↗ <span class="label">${esc(t("Notices"))}</span></a><a class="header-button" href="#/notifications" aria-label="${esc(t("Notifications"))}">♧<span id="notification-count"></span></a><a class="avatar" href="#/preferences" aria-label="${esc(t("Preferences"))}">${esc((S.profile.name || "P").slice(0, 2).toUpperCase())}</a></div></header><div id="offline"></div><main id="main" tabindex="-1"><div class="loading">${esc(t("Loading…"))}</div></main></div><nav class="mobile-nav" aria-label="Mobile navigation">${navHtml}</nav>`;
  document.documentElement.lang = S.profile.language;
  offlineBanner();
}
function offlineBanner() {
  const target = $("#offline");
  if (target)
    target.innerHTML = navigator.onLine
      ? ""
      : `<div class="offline-banner">${esc(t("You are offline. Reconnect to load current records."))}</div>`;
}
function observationText(note) {
  if (!note)
    return {
      title: t("Your workspace is up to date"),
      description: t("Review your plans whenever you are ready."),
      label: "Budget",
      destination: "#/budget",
    };
  if (note.kind === "receivable")
    return {
      title: note.data.title,
      description: `${money(note.data.amount_minor)} ${t("expected")}${note.data.due ? ` · ${t("due")} ${date(note.data.due)}` : ""}`,
      label: "Review customer balance",
      destination: note.destination,
    };
  if (note.kind === "goal")
    return {
      title: note.data.title,
      description: `${money(note.data.amount_minor)} ${t("left to save")}`,
      label: "Review savings goal",
      destination: note.destination,
    };
  if (note.kind === "price_low")
    return {
      title: note.data.title,
      description: `${priceMoney(note.data.amount_minor, note.data.currency)} · ${t("Lowest since tracking began")}`,
      label: "View details",
      destination: note.destination,
    };
  if (note.kind === "purchase")
    return {
      title: note.data.title,
      description: t(note.data.status).replaceAll("_", " "),
      label: "View details",
      destination: note.destination,
    };
  if (note.kind === "bill")
    return {
      title: note.data.title,
      description: `${money(note.data.amount_minor)} · ${t("due")} ${date(note.data.due)}`,
      label: "Review bill",
      destination: note.destination,
    };
  if (note.kind === "replacement")
    return {
      title: `${t("Replacement window")} · ${note.data.title}`,
      description: `${note.data.days} ${t("days")}`,
      label: "View details",
      destination: note.destination,
    };
  return {
    title: t("Payment verification"),
    description: t(note.data.status),
    label: "View details",
    destination: note.destination,
  };
}
function drawChart(id, points) {
  const canvas = document.getElementById(id);
  if (!canvas || !points.length) return;
  const bounds = canvas.parentElement.getBoundingClientRect(),
    ratio = window.devicePixelRatio || 1;
  canvas.width = bounds.width * ratio;
  canvas.height = bounds.height * ratio;
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  const width = bounds.width,
    height = bounds.height,
    left = 55,
    right = 12,
    top = 16,
    bottom = 33;
  const values = points.map((p) => p.balance_minor);
  let min = Math.min(...values),
    max = Math.max(...values);
  const gap = Math.max((max - min) * 0.2, 10000);
  min -= gap;
  max += gap;
  const x = (i) =>
      left + (i * (width - left - right)) / Math.max(points.length - 1, 1),
    y = (value) =>
      top + ((max - value) * (height - top - bottom)) / (max - min);
  ctx.font = "10px 'DM Sans', sans-serif";
  ctx.fillStyle = "#8b9383";
  ctx.strokeStyle = "#edf0e9";
  ctx.lineWidth = 1;
  for (let tick = 0; tick < 4; tick++) {
    const val = min + ((max - min) * tick) / 3,
      py = y(val);
    ctx.beginPath();
    ctx.moveTo(left, py);
    ctx.lineTo(width - right, py);
    ctx.stroke();
    ctx.fillText(
      `₹${Math.round(val / 100).toLocaleString("en-IN")}`,
      0,
      py + 4,
    );
  }
  [
    0,
    Math.floor(points.length / 3),
    Math.floor((points.length * 2) / 3),
    points.length - 1,
  ].forEach((i) => {
    ctx.textAlign = i === points.length - 1 ? "right" : "left";
    ctx.fillText(
      new Date(points[i].date).toLocaleDateString("en-IN", {
        day: "numeric",
        month: "short",
      }),
      x(i),
      height - 8,
    );
  });
  const gradient = ctx.createLinearGradient(0, top, 0, height - bottom);
  gradient.addColorStop(0, "#a8e63d55");
  gradient.addColorStop(1, "#a8e63d03");
  ctx.beginPath();
  ctx.moveTo(x(0), height - bottom);
  points.forEach((point, i) => ctx.lineTo(x(i), y(point.balance_minor)));
  ctx.lineTo(x(points.length - 1), height - bottom);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();
  ctx.beginPath();
  points.forEach((point, i) =>
    i
      ? ctx.lineTo(x(i), y(point.balance_minor))
      : ctx.moveTo(x(i), y(point.balance_minor)),
  );
  ctx.strokeStyle = "#88b742";
  ctx.lineWidth = 2.5;
  ctx.lineJoin = "round";
  ctx.stroke();
  const last = points.length - 1;
  ctx.beginPath();
  ctx.arc(x(last), y(points[last].balance_minor), 4, 0, Math.PI * 2);
  ctx.fillStyle = "#668c2b";
  ctx.fill();
  canvas.onpointermove = (event) => {
    const rect = canvas.getBoundingClientRect(),
      index = Math.max(
        0,
        Math.min(
          points.length - 1,
          Math.round(
            ((event.clientX - rect.left - left) / (width - left - right)) *
              (points.length - 1),
          ),
        ),
      ),
      tooltip = canvas.nextElementSibling;
    tooltip.style.display = "block";
    tooltip.style.left = `${Math.min(width - 140, Math.max(10, x(index) - 40))}px`;
    tooltip.style.top = "3px";
    tooltip.textContent = `${date(points[index].date)} · ${money(points[index].balance_minor)}`;
  };
  canvas.onpointerleave = () =>
    (canvas.nextElementSibling.style.display = "none");
}

function reminderTiming(task, day) {
  if (task.kind === "price_low")
    return { label: t("New price low"), tone: "price" };
  if (task.kind === "payment" && task.data.status === "checking")
    return { label: t("Payment under review"), tone: "urgent" };
  const days =
    task.kind === "replacement"
      ? task.data.days
      : (Date.parse(`${task.data.due?.slice(0, 10)}T00:00:00Z`) -
          Date.parse(`${day}T00:00:00Z`)) /
        86400000;
  if (!Number.isFinite(days)) return null;
  if (days < 0) return { label: t("Overdue"), tone: "urgent" };
  if (days === 0) return { label: t("Due today"), tone: "urgent" };
  if (days === 1) return { label: t("Due tomorrow"), tone: "soon" };
  return {
    label: t("Due in {days} days").replace("{days}", days),
    tone: days <= 3 ? "soon" : "planned",
  };
}

function reminderBadge(timing) {
  return timing
    ? `<span class="reminder-badge" data-tone="${timing.tone}">${esc(timing.label)}</span>`
    : "";
}

function agentCoverage() {
  const entries = [
    ["Bills & planning", "Bills, budgets and savings goals", "budget"],
    ["Cart Intelligence", "Watched prices and new lows", "purchases/before"],
    ["During Payment", "Checkout and payment verification", "purchases/during"],
    ["After Payment", "Delivery, warranties and returns", "purchases/after"],
  ];
  return `<details class="agent-coverage"><summary>${esc(t("What Tara can help with"))}</summary><ul>${entries.map(([title, description, path]) => `<li><a href="#/${path}">${esc(t(title))} <span aria-hidden="true">↗</span></a><small>${esc(t(description))}</small></li>`).join("")}</ul></details>`;
}

const dailyChecklistViewKey = "contextiq.daily-checklist.compact";
let dailyChecklistCollapsed = false;
try {
  dailyChecklistCollapsed =
    localStorage.getItem(dailyChecklistViewKey) === "yes";
} catch {
  // The current page can still switch views if browser storage is disabled.
}

function toggleDailyChecklist() {
  const toggle = $(".daily-toggle");
  const body = $("#daily-checklist-body");
  const summary = $(".daily-compact");
  if (!toggle || !body || !summary) return;
  dailyChecklistCollapsed = !dailyChecklistCollapsed;
  toggle.setAttribute("aria-expanded", String(!dailyChecklistCollapsed));
  toggle.textContent = t(dailyChecklistCollapsed ? "Show list" : "Hide list");
  body.hidden = dailyChecklistCollapsed;
  summary.hidden = !dailyChecklistCollapsed;
  try {
    localStorage.setItem(
      dailyChecklistViewKey,
      dailyChecklistCollapsed ? "yes" : "no",
    );
  } catch {
    // Keep the in-memory preference for the current tab.
  }
  guide.update();
}

function dailyChecklist(data) {
  const tasks = data.suggestions || [];
  const done = tasks.filter((task) => task.completed).length;
  const ordered = [
    ...tasks.filter((task) => !task.completed),
    ...tasks.filter((task) => task.completed),
  ];
  const next = data.focus ? observationText(data.focus) : null;
  const compact = next
    ? `<span>${esc(t("Next up"))}</span><a class="daily-link" href="${esc(next.destination)}">${esc(next.title)} <span aria-hidden="true">↗</span></a>${reminderBadge(reminderTiming(data.focus, data.task_date))}`
    : `<span>${esc(t(tasks.length ? "All tasks done" : "No tasks need your attention today."))}</span>`;
  return `<div class="section-top daily-header"><h2 id="today-checklist-title" tabindex="-1">${esc(t("Today's to-do list"))}</h2><div class="daily-header-controls">${tasks.length ? `<span class="daily-progress">${done}/${tasks.length} ${esc(t("done"))}</span>` : ""}<button class="daily-toggle" data-checklist-toggle type="button" aria-controls="daily-checklist-body" aria-expanded="${!dailyChecklistCollapsed}">${esc(t(dailyChecklistCollapsed ? "Show list" : "Hide list"))}</button></div></div><div class="daily-compact" ${dailyChecklistCollapsed ? "" : "hidden"}>${compact}</div><div id="daily-checklist-body" ${dailyChecklistCollapsed ? "hidden" : ""}>${
    tasks.length
      ? `<ul class="daily-tasks">${ordered
          .map((task) => {
            const content = observationText(task);
            const next = task.id === data.focus?.id;
            const detail =
              next && task.kind === "payment" && task.data.status === "checking"
                ? t(
                    "Open the payment issue to see what has been verified so far.",
                  )
                : content.description;
            return `<li class="daily-task${task.completed ? " daily-done" : ""}" ${next ? 'data-next-task="true" aria-current="step"' : ""}><input type="checkbox" data-daily-task="${esc(task.id)}" aria-label="${esc(t("Mark done") + ": " + content.title)}" ${task.completed ? "checked" : ""}><div>${next ? `<span class="daily-next-label">${esc(t("Next up"))}</span>` : ""}<div class="daily-task-title"><h3>${esc(content.title)}</h3>${task.completed ? "" : reminderBadge(reminderTiming(task, data.task_date))}</div><p>${esc(detail)}</p><a class="daily-link" href="${esc(content.destination)}">${esc(t(content.label))} →</a></div></li>`;
          })
          .join("")}</ul>`
      : `<p class="daily-empty">${esc(t("No tasks need your attention today."))}</p>`
  }${agentCoverage()}</div>`;
}

async function home() {
  const data = await api("/dashboard");
  S.dashboard = data;
  const f = data.finance,
    hour = new Date().getHours(),
    greeting =
      hour < 12
        ? "Good morning"
        : hour < 18
          ? "Good afternoon"
          : "Good evening";
  return `${head(`${t(greeting)}, ${S.profile.name}.`, "A little clarity for your day.", `<span class="date-label">${date(new Date())}</span>`)}<section class="focus-card daily-checklist reminder-section" aria-labelledby="today-checklist-title">${dailyChecklist(data)}</section><div class="overview"><section class="balance-card"><div class="section-top"><span style="font-size:13px">${esc(t("Available funds"))}</span><span class="muted" style="font-size:12px">${esc(t(data.workspace === "all" ? "Unified" : data.workspace === "business" ? "Business" : "Personal"))} ↗</span></div><div class="amount">${money(f.balance_minor)}</div><span class="balance-note">${esc(t("Recorded demo funds"))} · INR</span><div class="balance-movement"><div><div class="movement-label"><span class="circle-icon">↙</span>${esc(t("Money in"))}</div><div class="movement-value">${money(f.income_minor)}</div></div><div><div class="movement-label"><span class="circle-icon">↗</span>${esc(t("Money out"))}</div><div class="movement-value">${money(f.expense_minor)}</div></div></div></section><section class="chart-card"><div class="section-top"><h3>${esc(t("Balance over time"))}</h3><span class="period">${esc(t("Last 30 days"))}</span></div><div class="chart-wrap"><canvas id="balance-chart" role="img" aria-label="Ledger-derived balance over the last 30 days"></canvas><span class="chart-tip"></span></div><div class="reconciliation">${money(f.opening_minor)} + ${money(f.income_minor)} − ${money(f.expense_minor)} = <strong>${money(f.balance_minor)}</strong></div></section></div><div class="quick-actions"><a class="quick-action" href="#/scan"><span class="quick-icon">▦</span><div><h3>${esc(t("Scan & Pay"))}</h3><p>${esc(t("Review a QR before you pay"))}</p></div><span class="arrow">↗</span></a><a class="quick-action" href="#/qr"><span class="quick-icon">＋</span><div><h3>${esc(t("Create Dynamic QR"))}</h3><p>${esc(t("An amount or a complete bill"))}</p></div><span class="arrow">↗</span></a></div><div class="bottom-note">◌ ${esc(t("Fictional data. Simulated payments."))} · ${date(data.as_of)}</div>`;
}
function tile(title, description, path, icon) {
  return `<a class="tile" href="#/${path}"><span class="tile-icon" aria-hidden="true">${icon}</span><h2>${esc(t(title))}</h2><p>${esc(t(description))}</p><span class="tile-link">${esc(t("View details"))}<span>↗</span></span></a>`;
}
async function purchasesPage() {
  const sub = S.route[1];
  if (!sub)
    return `${head("Purchases", "", link("Browse BrightMart", "store", "green"))}<div class="grid">${tile("Before Payment", "Tracked items, price history and affordability", "purchases/before", "◴")}${tile("During Payment", "Authorization, status and recovery", "purchases/during", "⇄")}${tile("After Payment", "Delivery, warranty and purchase protection", "purchases/after", "▣")}</div>`;
  if (sub === "before") return watchPage();
  if (sub === "item") return itemPage(S.route[2]);
  if (sub === "after") {
    const items = await api("/purchases");
    return `${back("purchases")}${head("After Payment")}${items.length ? `<div class="panel">${items.map((item) => `<a class="list-row" href="#/purchases/item/${item.id}"><div class="list-leading"><span class="quick-icon">▣</span><div><h3>${esc(item.name)}</h3><p>BrightMart · ${item.quantity} × ${money(item.unit_minor)}</p></div></div><div>${status(item.state)}<span class="arrow"> ↗</span></div></a>`).join("")}</div>` : empty()}`;
  }
  const rows = (await api("/invoices")).filter((row) =>
    ["open", "authorized", "provider_checkout"].includes(row.status),
  );
  const handoff = await sharedCartReview("checkout");
  return `${back("purchases")}${head("During Payment", "Review or verify an invoice")}${handoff}${rows.length ? `<div class="panel">${rows.map(invoiceRow).join("")}</div>` : handoff ? "" : empty("purchases/before", "Cart Intelligence")}`;
}

function invoiceRow(row) {
  return `<a class="list-row" href="#/invoice/${row.id}"><div><h3>${esc(row.items.map((i) => i.name).join(", "))}</h3><p>${esc(t("Invoice"))} #${row.id.slice(0, 8)} · ${esc(t("Version"))} ${row.version}</p></div><div class="list-amount">${money(row.total_minor)}<div style="margin-top:8px">${status(row.status)}</div></div></a>`;
}
async function invoicePage() {
  const row = await api(`/invoices/${S.route[1]}`);
  S.invoice = row;
  const a = row.affordability;
  return `${back("purchases/before")}${head("Invoice", `BrightMart · #${row.id.slice(0, 8)} · ${t("Version")} ${row.version}`, status(row.status))}<div class="detail-grid"><div><section class="panel"><h2>${esc(t("Review and authorize"))}</h2>${row.items.map((item) => `<div class="list-row"><div><h3>${esc(item.name)}</h3><p>${item.quantity} × ${money(item.unit_minor)}</p></div><strong>${money(item.unit_minor * item.quantity)}</strong></div>`).join("")}${kv("Total", money(row.total_minor))}${kv("Recipient", "BrightMart Electronics")}${row.status === "paid" ? kv("Payment method", esc(t(row.checkout.existing_method ? row.checkout.methods[row.checkout.existing_method] : row.checkout.methods[row.checkout.simulated_method] ? row.checkout.methods[row.checkout.simulated_method] + " · " + t("Demo") : "Mock payment"))) : ""}${kv("Purpose", esc(t(row.purpose === "business" ? "Business" : "Personal")))}${["open", "authorized", "provider_checkout"].includes(row.status) ? checkoutForm(row) : row.status === "paid" ? `<div class="notice">✓ ${esc(t("Payment confirmed"))}</div><div class="actions">${link("View purchases", "purchases/after", "green")}${link("Complete briefcase", `activity/briefcase/${row.case_id}`, "white")}</div>` : `<div class="notice warn">${esc(t(row.status))}</div>`}</section><section class="panel"><h3>${esc(t("Purchase terms"))}</h3><p class="muted" style="font-size:13px;margin-top:14px">${esc(row.policy)}</p></section></div><div><section class="panel"><h3>${esc(t("Budget"))}</h3>${kv("Available funds", money(a.funds_minor))}${kv("Recorded commitments", money(a.bills_minor))}${a.allocated_minor ? kv("Other planned reserves", money(a.allocated_minor)) : ""}${kv(row.status === "paid" ? "Flexible funds now" : "After this purchase", `<span class="${a.remaining_minor < 0 ? "negative" : "positive"}">${money(a.remaining_minor)}</span>`)}${a.remaining_minor < 0 ? `<div class="notice warn">${esc(t("This purchase exceeds your flexible funds."))}</div>` : ""}${a.alternative ? button("Consider Everyday headphones", "alternative", "", "green") : ""}</section><section class="qr-box"><h3>${esc(t(row.kind === "payment" ? "Amount-based QR" : "Itemized bill QR"))}</h3><div id="qr-image" style="margin-top:20px"></div><p class="field-hint">${esc(t("Expires"))} ${date(row.expires_at)}</p><div class="actions" style="justify-content:center;margin-top:15px">${button("Copy QR text", "copy-qr", "", "small white")}${link("Scan & Pay", "scan", "small white")}</div>${row.status === "open" ? `<div class="actions" style="justify-content:center;margin-top:12px">${button("Regenerate", "regenerate", row.id, "small ghost")}${button("Cancel invoice", "cancel-invoice", row.id, "small ghost")}</div>` : ""}</section></div></div>`;
}
function noticeDemo() {
  return `<div class="notice">${esc(t("Fictional data. Simulated payments."))}</div>`;
}
function qrPage() {
  return `${back("home")}${head("Create Dynamic QR")}${noticeDemo()}<section class="panel" style="max-width:670px"><form id="qr-form">${selectField(
    "Invoice",
    "kind",
    [
      ["payment", "Amount-based QR"],
      ["itemized", "Itemized bill QR"],
    ],
    "payment",
  )}${field("Message", "description", "Payment request", "text", "required")}${field("Amount", "amount", 100, "number", "min=0.01 step=0.01 required")}${selectField(
    "Purpose",
    "purpose",
    [
      ["personal", "Personal"],
      ["business", "Business"],
    ],
    "personal",
  )}<p class="field-hint">${esc(t("Itemized bill QR"))} → ${esc(t("Cart"))}</p><div class="actions" style="margin-top:22px"><button type="submit" class="btn green">${esc(t("Create Dynamic QR"))}</button></div></form></section>`;
}
function scanPage() {
  return `${back("home")}${head("Scan & Pay")}<section class="panel" style="max-width:700px"><form id="scan-form"><label for="token">${esc(t("Paste QR text"))}</label><textarea id="token" name="token" required placeholder="ciq1.… / upi://pay?…"></textarea><div class="actions" style="margin-top:20px"><button class="btn green" type="submit">${esc(t("Verify QR"))}</button>${button("Use camera", "camera", "", "white")}</div></form><video class="video hide" id="scan-video" autoplay playsinline></video><div id="scan-result"></div></section>`;
}
async function itemPage(id) {
  const item = await api(`/purchases/${id}`);
  S.item = item;
  return `${back("purchases/after")}${head(item.name, "", status(item.state))}<div class="detail-grid"><section class="panel"><h2>${esc(t("Delivery"))}</h2>${kv("Recipient", esc(item.merchant))}${kv("Quantity", `${item.delivered_quantity} / ${item.quantity}`)}${kv("Amount", money(item.unit_minor * item.quantity))}${kv("Date", item.delivered_at ? date(item.delivered_at) : "—")}<div class="spacer"></div><h2>${esc(t("Returns & replacements"))}</h2>${item.replacement_days !== null ? `<div class="notice">${esc(t("Replacement window"))} · ${item.replacement_days} ${esc(t("days"))}</div>` : ""}${kv("Warranty", item.warranty_until ? date(item.warranty_until) : "—")}${kv("Returns & replacements", item.return_until ? date(item.return_until) : "—")}${item.request ? `<div class="notice">${status(item.request)}</div>` : ""}<div class="actions" style="margin-top:22px">${item.delivered_at ? `${button("Request replacement", "item-action", "replacement", "green")}${button("Request return", "item-action", "return", "white")}${button("Request warranty service", "item-action", "warranty", "white")}` : ""}</div></section><div><section class="panel"><h2>${esc(t("Complete briefcase"))}</h2><div class="spacer"></div>${link("Complete briefcase", `activity/briefcase/${item.case_id}`, "green")}<div class="actions" style="margin-top:15px">${button("Connect with seller", "connect", item.case_id, "white")}</div></section><section class="panel"><h3>${esc(t("Demo seller action"))}</h3><p class="field-hint">${esc(t("Fictional data. Simulated payments."))}</p><div class="actions" style="margin-top:18px">${button("Simulate shipment", "item-action", "ship", "white")}${button("Simulate delivery", "delivery-dialog", id, "white")}${item.request === "replacement_requested" ? button("Approve replacement", "item-action", "approve_replacement", "green") : ""}${button("Refund items", "refund-dialog", id, "white")}</div></section></div></div>`;
}
