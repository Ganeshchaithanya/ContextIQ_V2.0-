async function budgetPage() {
  const section = S.route[1];
  if (section === "business") return businessPage();
  if (!section)
    return `${head("Budget", "Make room for what matters.")}<div class="grid">${[
      [
        "Income & Expenses",
        "A clear view of your recorded money.",
        "income",
        "↗",
      ],
      ["Bills & Commitments", "Keep upcoming payments in view.", "bills", "▤"],
      [
        "Spending Allocation",
        "Give your available funds a purpose.",
        "allocation",
        "◫",
      ],
      [
        "Future Purchases",
        "Turn your next purchase into a plan.",
        "goals",
        "◎",
      ],
      [
        "EMI Commitments",
        "Understand installments and total cost.",
        "emi",
        "≋",
      ],
      [
        "Cash-flow Forecast",
        "Look ahead using recorded commitments.",
        "forecast",
        "↗",
      ],
    ]
      .concat(
        S.profile.configuration !== "personal" ||
          S.profile.features?.includes("business")
          ? [
              [
                "Business records",
                "Track customers, suppliers and invoices.",
                "business",
                "▣",
              ],
            ]
          : [],
      )
      .map(([title, description, path, icon]) =>
        tile(title, description, `budget/${path}`, icon),
      )
      .join("")}</div>`;
  if (section === "income") return historyPage();
  if (["bills", "business-bills"].includes(section)) {
    const all = await api("/bills");
    const rows = all.filter(
      (r) =>
        (!S.route[2] || r.id === S.route[2]) &&
        (section !== "business-bills" || r.purpose === "business"),
    );
    return `${back("budget")}${head("Bills & Commitments", "Recorded commitments", button("Add bill", "bill-dialog", "", "green"))}<section class="panel">${rows.map((r) => `<div class="list-row"><div><h3>${esc(r.title)}</h3><p>${date(r.due)} · ${esc(t(r.purpose === "business" ? "Business" : "Personal"))} · ${status(r.status)}</p></div><div class="list-amount">${money(r.amount_minor)}<div class="spacer"></div>${r.status === "open" ? button("Record payment", "bill-pay", r.id, "small white") : ""}</div></div>`).join("") || empty("budget", "Budget")}</section>`;
  }
  if (section === "forecast") {
    S.forecast = await api("/forecast");
    return `${back("budget")}${head("Cash-flow Forecast")}<section class="panel"><h3>${esc(t("Next 30 days"))}</h3><div class="chart-wrap"><canvas id="forecast-chart" role="img" aria-label="Forecast from recorded commitments"></canvas><span class="chart-tip"></span></div><div class="notice">${esc(t(S.forecast.basis))}</div></section>`;
  }
  const kind = { goals: "goal", allocation: "allocation", emi: "emi" }[section];
  if (!kind) throw new Error("Page not found");
  S.plans = (await api("/plans")).filter(
    (p) => p.kind === kind && (!S.route[2] || p.id === S.route[2]),
  );
  const title = {
    goal: "Future Purchases",
    allocation: "Spending Allocation",
    emi: "EMI Commitments",
  }[kind];
  return `${back("budget")}${head(title, "", button("Add plan", "plan-dialog", kind, "green"))}<div class="grid two">${S.plans
    .map((p) => {
      const d = p.data;
      let content = "";
      if (kind === "goal")
        content = `${kv("Saved", money(d.saved_minor))}${kv("Target", money(d.target_minor))}<div class="progress-track"><div style="width:${Math.min(100, (100 * d.saved_minor) / d.target_minor)}%"></div></div>${kv("Monthly contribution", money(d.contribution_minor || 0))}${d.target_date ? kv("Target date", date(d.target_date)) : ""}${button("Update savings", "savings-dialog", p.id, "white")}`;
      if (kind === "allocation")
        content = `${kv("Allocated", money(d.amount_minor))}<p class="field-hint">${esc(t("Allocation reserves planning space; it does not move money."))}</p>`;
      if (kind === "emi")
        content = `${kv("Monthly installment", money(d.installment_minor))}${kv("Total repayment", money(d.total_minor))}${kv("Total interest", money(d.interest_minor))}<div class="table-wrap"><table><thead><tr><th>${esc(t("Date"))}</th><th>${esc(t("Amount"))}</th><th>${esc(t("Status"))}</th></tr></thead><tbody>${d.schedule.map((row) => `<tr><td>${date(row.due)}</td><td>${money(row.amount_minor)}</td><td>${row.paid ? status("paid") : link("Review bill", `budget/bills/${row.bill_id}`, "small ghost")}</td></tr>`).join("")}</tbody></table></div><p class="field-hint">${esc(t(d.schedule_basis))}</p>`;
      return `<section class="panel"><h2>${esc(p.title)}</h2><p class="field-hint">${esc(t(p.purpose === "business" ? "Business" : "Personal"))}</p><div class="spacer"></div>${content}</section>`;
    })
    .join("")}</div>${!S.plans.length ? empty("budget", "Budget") : ""}`;
}

const businessKinds = [
  ["customer", "Customer"],
  ["supplier", "Supplier"],
  ["receivable", "Receivable"],
  ["supplier_invoice", "Supplier invoice"],
];

async function businessPage() {
  const data = await api("/business");
  const rows = data.records.filter(
    (row) => !S.route[2] || row.id === S.route[2],
  );
  return `${back("budget")}${head("Business records", "Track customers, suppliers and invoices.", button("Add business record", "business-dialog", "", "green"))}<section class="panel">${kv("Recorded business funds", money(data.finance.balance_minor))}${kv("Expected receivables", money(data.expected_minor))}${link("Business bills", "budget/business-bills", "small white")}</section>${
    rows.length
      ? `<section class="panel">${rows
          .map((row) => {
            const d = row.data;
            return `<div class="list-row"><div><h3>${esc(row.title)}</h3><p>${esc(t(businessKinds.find(([key]) => key === row.kind)[1]))} · ${status(d.status)}</p><p>${esc(d.contact)}${d.due ? ` · ${date(d.due)}` : ""}</p>${d.notes ? `<p>${esc(d.notes)}</p>` : ""}${d.difference_minor ? `<p class="negative">${esc(t("Difference from expected amount"))} · ${money(d.difference_minor)}</p>` : ""}</div><div>${d.amount_minor ? `<div class="list-amount">${money(d.amount_minor)}</div>` : ""}${d.amount_minor && d.status === "open" ? button("Record payment", "business-pay", row.id, "small white") : ""}</div></div>`;
          })
          .join("")}</section>`
      : empty("budget", "Budget")
  }`;
}

async function historyPage() {
  const rows = await api("/history");
  return `${back("activity")}${head("Transaction History", "", button("Add record", "ledger-dialog", "", "green"))}<input class="search" id="history-search" aria-label="Search transaction history" placeholder="${esc(t("Search transactions"))}"><section class="panel" id="history-list">${rows.map((r) => `<div class="list-row" data-search="${esc(`${r.payee} ${r.category} ${r.description}`.toLowerCase())}"><div><h3>${esc(r.payee)}</h3><p>${date(r.date)} · ${esc(t(r.purpose === "business" ? "Business" : "Personal"))} · ${esc(r.category)}</p><p>${esc(r.description)} · ${esc(r.source)}</p>${r.case_id ? link("Complete briefcase", `activity/briefcase/${r.case_id}`, "small ghost") : ""}</div><strong class="${r.amount_minor < 0 ? "positive" : "negative"}">${r.amount_minor < 0 ? "+" : "−"}${money(Math.abs(r.amount_minor))}</strong></div>`).join("")}</section>`;
}

async function activityPage() {
  const section = S.route[1];
  if (!section)
    return `${head("Activity", "Everything connected to your money.")}<div class="grid">${tile("Transaction History", "Your recorded income, spending and refunds.", "activity/history", "↗")}${tile("Purchase Briefcases", "Agreements, timelines and evidence together.", "activity/briefcases", "▣")}${tile("Payment Issues", "Follow the original payment to its resolution.", "activity/issues", "◎")}</div>`;
  if (section === "history") return historyPage();
  if (section === "briefcases") {
    const rows = (await api("/invoices")).filter((r) => r.case_id);
    return `${back("activity")}${head("Purchase Briefcases")}<section class="panel">${rows.map((r) => `<a class="list-row" href="#/activity/briefcase/${r.case_id}"><div><h3>${esc(r.items.map((i) => i.name).join(", "))}</h3><p>#${esc(r.case_id)}</p></div>${status(r.status)}<strong>${money(r.total_minor)} →</strong></a>`).join("") || empty()}</section>`;
  }
  if (section === "briefcase") {
    const data = await api(`/briefcases/${S.route[2]}`),
      c = data.case;
    return `${back("activity/briefcases")}${head(c.title, `${c.merchant} · #${c.id}`, status(c.payment_state))}<div class="detail-grid"><section class="panel"><h2>${esc(t("Timeline"))}</h2><div class="spacer"></div><div class="timeline">${data.events.map((e) => `<div class="timeline-item"><p>${esc(t(e.type.replaceAll("_", " ")))}</p><small>${date(e.at)} · ${esc(e.source)}</small></div>`).join("")}</div></section><div><section class="panel"><h2>${esc(t("Agreement"))}</h2>${kv("Amount", money(Math.round(c.amount * 100)))}${kv("Recipient", esc(c.merchant))}<p class="field-hint">${esc(typeof data.agreement?.terms === "string" ? data.agreement.terms : t("Review the merchant terms below."))}</p>${data.policy?.original_text ? `<details style="margin-top:14px"><summary>${esc(t("Purchase terms"))}</summary><p>${esc(data.policy.original_text)}</p></details>` : ""}<div class="actions" style="margin-top:18px">${button("Check original payment", "investigate", c.id, "green")}${button("Connect with seller", "connect", c.id, "white")}</div></section><section class="panel"><h2>${esc(t("Evidence"))}</h2>${data.evidence.map((e) => `<div class="list-row"><div><h3>${esc(e.summary)}</h3><p>${esc(e.source)} · ${esc(t(e.provenance))} · ${date(e.at)}</p><details><summary>${esc(t("Evidence reference"))}</summary><p style="overflow-wrap:anywhere">${esc(e.hash)}</p></details></div></div>`).join("")}</section></div></div>`;
  }
  if (section === "issues") {
    const rows = (await api("/incidents")).filter(
      (r) => !S.route[2] || r.id === S.route[2],
    );
    return `${back("activity")}${head("Payment Issues")}<div class="grid two">${rows.map((r) => `<section class="panel"><h2>${esc(t("Payment verification"))}</h2><p class="field-hint">${date(r.created_at)} · ${esc(r.provider)}</p><div class="spacer"></div>${status(r.status)}<div class="timeline" style="margin-top:24px">${r.steps.map((step) => `<div class="timeline-item"><p>${esc(typeof step === "string" ? t(step) : JSON.stringify(step))}</p></div>`).join("")}</div>${link("Complete briefcase", `activity/briefcase/${r.case_id}`, "green")}</section>`).join("")}</div>${!rows.length ? empty("purchases/during", "During Purchase") : ""}`;
  }
  throw new Error("Page not found");
}

async function notificationsPage() {
  const data = await api("/dashboard");
  return `${head("Notifications")}<section class="panel">${
    data.observations
      .map((n) => {
        const text = observationText(n);
        return `<a class="list-row" href="${esc(n.destination)}" data-read="${esc(n.id)}"><div><h3>${n.read ? "" : "● "}${esc(text.title)}</h3><p>${esc(text.description)}</p></div><span>→</span></a>`;
      })
      .join("") || empty("home", "Home")
  }</section>`;
}

async function noticesPage() {
  S.notices = await api("/notices");
  const tab = S.route[1] || "inbox";
  const rows = S.notices.filter((n) =>
    tab === "drafts"
      ? n.status === "draft"
      : n.status !== "draft" && n.direction === tab,
  );
  return `${head("Notices", "In-app messages between your demo buyer and seller.", button("Draft notice", "notice-dialog", "", "green"))}<div class="tabs">${["inbox", "sent", "drafts"].map((key) => `<a class="${tab === key ? "active" : ""}" href="#/notices/${key}">${esc(t(key[0].toUpperCase() + key.slice(1)))}</a>`).join("")}</div>${rows.map((n) => `<section class="panel"><div class="section-top"><h2>${esc(n.subject)}</h2>${status(n.status)}</div><p style="white-space:pre-wrap;margin-top:20px">${esc(n.message)}</p><p class="field-hint">${date(n.created_at)} · ${esc(t("In-app only"))}</p>${n.status === "draft" ? `<div class="actions" style="margin-top:20px">${button("Review and send", "notice-review", n.id, "green")}</div>` : ""}</section>`).join("") || empty("notices/drafts", "Drafts")}`;
}

async function askPage() {
  S.messages = await api("/ask");
  return `<div class="chat"><div class="chat-intro"><span class="ask-symbol" style="font-size:34px">✦</span>${head("Ask ContextIQ", "A clearer answer, grounded in your records.")}<div class="prompts">${["What should I focus on today?", "Can I afford this purchase?", "What bills are due?"].map((q) => button(q, "prompt", t(q))).join("")}</div></div><div id="messages">${S.messages.map(messageHtml).join("")}</div><form id="ask-form" class="chat-form"><input name="message" required maxlength="2000" aria-label="${esc(t("Ask a question"))}" placeholder="${esc(t("Ask a question"))}">${S.profile.voice_enabled ? button("Voice", "voice", "", "white") : ""}<button type="submit" class="btn green">${esc(t("Send"))} ↗</button></form><p class="field-hint">${esc(t("Answers use your demo records. No money moves through chat."))}</p></div>`;
}
function messageHtml(row) {
  return `<div class="message user">${esc(row.question)}</div><div class="message assistant">${esc(row.answer)}<div class="actions"><a class="btn small white" href="${esc(row.destination)}">${esc(t("View details"))} ↗</a>${S.profile.voice_enabled ? button("Read aloud", "speak", row.answer, "small ghost") : ""}</div><details><summary class="field-hint">${esc(t("Evidence references"))}</summary><p class="field-hint">${esc(row.evidence.join(" · "))}</p></details></div>`;
}

async function preferencesPage() {
  const p = S.profile;
  return `${head("Preferences", "A workspace that fits your life.")}<section class="panel"><form id="preferences-form"><div class="form-grid">${field("What should we call you?", "name", p.name, "text", "required maxlength=80")}${selectField(
    "Language",
    "language",
    [
      ["en", "English"],
      ["hi", "हिन्दी"],
      ["kn", "ಕನ್ನಡ"],
    ],
    p.language,
  )}${selectField("Occupation", "occupation", occupations, p.occupation)}${selectField("How do you manage your money?", "configuration", configurations, p.configuration)}${field("Income frequency (optional)", "income_frequency", p.income_frequency || "")}${field("Business type", "business_type", p.business_type || "")}${field("Workday starts (hour)", "work_start", p.work_start, "number", "min=0 max=23")}${field("Workday ends (hour)", "work_end", p.work_end, "number", "min=0 max=23")}</div><h3>${esc(t("What matters most to you?"))}</h3><div class="form-grid">${[
    ["budget", "Budget"],
    ["purchases", "Purchases"],
    ["goals", "Future Purchases"],
    ["emi", "EMI Commitments"],
    ["business", "Business"],
  ]
    .map(([key, label]) =>
      check(label, `feature-${key}`, (p.features || []).includes(key)),
    )
    .join(
      "",
    )}</div>${check("Automatically choose a workspace using activity and working hours", "context_consent", p.context_consent)}${check("Voice assistance", "voice_enabled", p.voice_enabled)}${check("Learn from my confirmed preferences", "learning_enabled", p.learning_enabled)}<div class="actions" style="margin-top:20px"><button class="btn green" type="submit">${esc(t("Save preferences"))}</button></div></form></section><section class="panel"><h3>${esc(t("Reset my demo"))}</h3><p class="field-hint">${esc(t("Start a fresh private workspace. Other visitors are unaffected."))}</p><div class="actions" style="margin-top:15px">${button("Reset my demo", "reset-review", "", "white")}</div></section>`;
}

async function merchantPage() {
  const data = await api("/merchant");
  return `${head("Merchant desk", "BrightMart Electronics · Demo seller")}${noticeDemo()}<div class="stat-row"><div class="stat"><p>${esc(t("Sales"))}</p><div class="amount">${money(data.sales_minor)}</div></div><div class="stat"><p>${esc(t("Refunds"))}</p><div class="amount">${money(data.refunds_minor)}</div></div><div class="stat"><p>${esc(t("Orders"))}</p><div class="amount">${data.orders.length}</div></div></div><section class="panel">${data.orders.map((r) => `<div class="list-row"><div><h3>${esc(r.title)}</h3><p>#${r.id} · ${status(r.payment_state)}</p><div class="actions" style="margin-top:12px">${r.items.map((i) => link(i.name, `purchases/item/${i.id}`, "small white")).join("")}</div></div><strong>${money(r.amount_minor)}</strong></div>`).join("") || empty()}</section>${button("Draft notice", "notice-dialog", "seller", "green")}`;
}

async function render() {
  guide.clear();
  stopCamera();
  S.route = (
    location.hash.replace(/^#\//, "") ||
    (location.pathname === "/store" ? "store" : "home")
  )
    .split("?")[0]
    .split("/");
  if (!S.csrf) return welcome();
  if (!S.profile.onboarded) return onboarding();
  if (S.route[0] === "store") return window.location.assign("/store");
  if (S.route[0] === "cart") return navigate("purchases/before");
  const renderId = (S.renderId = (S.renderId || 0) + 1);
  shell();
  try {
    const pages = {
      home,
      purchases: purchasesPage,
      budget: budgetPage,
      activity: activityPage,
      invoice: invoicePage,
      qr: qrPage,
      scan: scanPage,
      notifications: notificationsPage,
      notices: noticesPage,
      ask: askPage,
      preferences: preferencesPage,
      watch: watchPage,
      merchant: merchantPage,
    };
    const page = pages[S.route[0]];
    if (!page) throw new Error("Page not found");
    const html = await page();
    if (renderId !== S.renderId) return;
    $("#main").innerHTML = html;
    document.title = `${t(phaseLabel(S.route[0]))} · ContextIQ`;
    if (S.route[0] === "home")
      drawChart("balance-chart", S.dashboard.finance.chart);
    if (S.route[1] === "forecast")
      drawChart("forecast-chart", S.forecast.points);
    if ($("#qr-image")) {
      const qr = qrcode(0, "M");
      qr.addData(S.invoice.qr_token);
      qr.make();
      $("#qr-image").innerHTML = qr.createImgTag(4, 8, "Invoice QR");
    }
    if ($("#messages"))
      $("#messages").lastElementChild?.scrollIntoView({ block: "nearest" });
    window.scrollTo(0, 0);
    guide.update();
  } catch (error) {
    if (renderId !== S.renderId) return;
    $("#main").innerHTML =
      `<section class="error-page"><h2>${esc(t("Unable to load this page"))}</h2><p>${esc(error.message)}</p>${button("Try again", "reload", "", "green")}${link("Home", "home", "white")}</section>`;
  }
}
