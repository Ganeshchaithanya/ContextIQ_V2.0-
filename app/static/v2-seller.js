(function () {
  "use strict";
  // Seller back office: receivables, invoices, customers, cash forecast and bills.
  // Loaded after v2.js and v2-pages.js; uses their globals (S, api, esc, t, head, back, toast, render, navigate).
  // Every request goes to /api/v2/seller/... (see app/v2_seller.py). Money is paise on the wire.

  const TABS = [
    ["seller", "Dashboard"],
    ["seller/invoices", "Invoices"],
    ["seller/customers", "Customers"],
    ["seller/forecast", "Cash forecast"],
    ["seller/bills", "Bills"],
    ["seller/settings", "Business settings"],
    ["knowledge", "Knowledge base"],
  ];
  const PAYMENT_METHODS = [["upi", "UPI"], ["bank", "Bank transfer"], ["cash", "Cash"], ["cheque", "Cheque"]];
  const METHOD_LABEL = Object.fromEntries(PAYMENT_METHODS);
  const CHIP = {
    draft: ["Draft", "draft"],
    sent: ["Awaiting payment", "sent"],
    part_paid: ["Part paid", "part"],
    paid: ["Paid", "paid"],
    cancelled: ["Cancelled", "cancelled"],
  };

  let lastAlerts = [];
  let lineSeq = 0;

  // ---------- formatting ----------
  // Indian grouping (₹1,23,456) via en-IN; paise shown only when present.
  function rupee(minor) {
    const value = Math.abs(Math.round(Number(minor) || 0));
    const whole = Math.floor(value / 100);
    const paise = value % 100;
    const digits = new Intl.NumberFormat("en-IN").format(whole);
    return `${(Number(minor) || 0) < 0 ? "−" : ""}₹${digits}${paise ? `.${String(paise).padStart(2, "0")}` : ""}`;
  }
  const todayIso = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Kolkata" });
  const shiftIso = (iso, days) => {
    const d = new Date(`${iso}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() + days);
    return d.toISOString().slice(0, 10);
  };
  const longDate = (iso) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const shortDate = (iso) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });
  const enc = (value) => encodeURIComponent(value);
  const toPaise = (value) => Math.round(Number(value) * 100);
  const routeQuery = () => new URLSearchParams(location.hash.split("?")[1] || "");
  const priorityKey = (p) => (p >= 85 ? "high" : p >= 60 ? "medium" : "low");

  // ---------- small view helpers ----------
  function chip(invoice) {
    if (invoice.overdue) return `<span class="seller-chip overdue">Overdue · ${invoice.days_overdue} days</span>`;
    const [label, kind] = CHIP[invoice.status] || [invoice.status, "draft"];
    return `<span class="seller-chip ${kind}">${esc(t(label))}</span>`;
  }
  function emptyState(title, body, actions = []) {
    return `<section class="panel seller-empty"><h2>${esc(t(title))}</h2><p>${esc(t(body))}</p>${
      actions.length ? `<div class="actions">${actions.map(([href, label, kind]) => `<a class="btn ${kind}" href="${esc(href)}">${esc(t(label))}</a>`).join("")}</div>` : ""
    }</section>`;
  }
  function sellerTabs(current) {
    return `<nav class="tabs seller-tabs" aria-label="Receivables sections">${TABS.map(([key, label]) =>
      `<a href="#/${key}" ${key === current ? 'class="active" aria-current="page"' : ""}>${esc(t(label))}</a>`).join("")}</nav>`;
  }
  function stat(label, value, tone = "") {
    return `<div class="stat"><p>${esc(t(label))}</p><div class="amount ${tone}">${value}</div></div>`;
  }

  // ---------- dashboard: who owes me? ----------
  function alertItem(item, index) {
    const buttons = [];
    if (item.invoice_id) buttons.push(`<a class="btn small white" href="#/seller/invoices/${enc(item.invoice_id)}">Open invoice</a>`);
    if (item.reminder) {
      buttons.push(`<button type="button" class="btn small green" data-seller-action="copy-alert" data-id="${index}">Copy reminder</button>`);
      if (item.reminder.whatsapp_url)
        buttons.push(`<a class="btn small ghost" href="${esc(item.reminder.whatsapp_url)}" target="_blank" rel="noopener">Open WhatsApp</a>`);
    }
    if (item.kind === "cash_gap") buttons.push(`<a class="btn small white" href="#/seller/forecast">See cash forecast</a>`);
    if (item.kind === "bill_due") buttons.push(`<a class="btn small white" href="#/seller/bills">View bills</a>`);
    const key = priorityKey(item.priority);
    const label = { high: "High priority", medium: "Medium priority", low: "Low priority" }[key];
    return `<li class="seller-alert" data-priority="${key}"><div><span class="seller-chip ${key}">${esc(t(label))}</span><h3>${esc(item.action)}</h3><p>${esc(item.detail)}</p></div><div class="actions">${buttons.join("")}</div></li>`;
  }

  async function dashboardView() {
    const [aging, alerts, cash] = await Promise.all([api("/seller/receivables/aging"), api("/seller/alerts"), api("/seller/forecast?horizon_days=30")]);
    lastAlerts = alerts.alerts;
    window.ContextIQSeller.focus = alerts.alerts[0] || null;
    const overdue = aging.invoices.filter((row) => row.overdue);
    const overdueTotal = overdue.reduce((sum, row) => sum + row.balance_minor, 0);
    const lateClients = new Set(overdue.map((row) => row.customer.id)).size;
    const buckets = [["0-7", "0–7 days"], ["8-30", "8–30 days"], ["31+", "31+ days"]];
    const bucketHtml = buckets.map(([key, label]) => {
      const b = aging.buckets[key];
      return `<div class="panel seller-bucket"><h3>${esc(t(label))} overdue</h3><p>${plural(b.count, "invoice")}</p><strong class="num">${rupee(b.amount_minor)}</strong></div>`;
    }).join("");
    const agingTable = aging.invoices.length
      ? `<div class="table-wrap"><table class="seller-table"><caption>Open invoices, most overdue first</caption><thead><tr><th scope="col">Invoice</th><th scope="col">Customer</th><th scope="col">Due</th><th scope="col">Days overdue</th><th scope="col" class="num">Balance</th><th scope="col"><span class="sr-only">Action</span></th></tr></thead><tbody>${
          aging.invoices.map((row) => `<tr><td>${esc(row.number)}</td><td>${esc(row.customer.name)}</td><td>${longDate(row.due_date)}</td><td>${row.days_overdue ? row.days_overdue : "Not yet due"}</td><td class="num">${rupee(row.balance_minor)}</td><td><a class="btn small ghost" href="#/seller/invoices/${enc(row.id)}">Open<span class="sr-only"> ${esc(row.number)}</span></a></td></tr>`).join("")
        }</tbody></table></div>`
      : emptyState("No money is owed to you yet", "Create an invoice for a customer and send it. It will show up here with its age.", [["#/seller/invoices/new", "New invoice", "green"], ["#/seller/customers", "Add a customer", "white"]]);
    const alertList = alerts.alerts.length
      ? `<ol class="seller-alerts">${alerts.alerts.map(alertItem).join("")}</ol>`
      : `<p class="field-hint">No alerts right now. Overdue invoices, bills due soon and cash gaps will appear here.</p>`;
    return {
      title: "Who owes me?",
      subtitle: "Receivables, late payers and the next thing to do.",
      action: `<a class="btn green" href="#/seller/invoices/new">New invoice</a>`,
      html: `<div class="stat-row seller-stats">${stat("Recorded cash", rupee(cash.opening_minor))}${stat("Total receivable", rupee(aging.total_outstanding_minor))}${stat("Overdue", rupee(overdueTotal), "negative")}${stat("Late clients", String(lateClients))}</div>
        <section class="panel"><h2>${esc(t("Aging"))}</h2><div class="seller-buckets">${bucketHtml}</div><div class="spacer"></div>${agingTable}</section>
        <section class="panel" aria-labelledby="seller-alerts-title"><h2 id="seller-alerts-title">${esc(t("Next actions"))}</h2>${alertList}</section>`,
    };
  }

  // ---------- invoices ----------
  function plural(n, word) {
    return `${n} ${word}${n === 1 ? "" : "s"}`;
  }

  async function invoicesList() {
    const rows = await api("/seller/invoices");
    if (!rows.length)
      return {
        title: "Invoices",
        subtitle: "Every invoice, with its status in words.",
        action: `<a class="btn green" href="#/seller/invoices/new">New invoice</a>`,
        html: emptyState("No invoices yet", "Create a draft for a customer. Review a draft, share it with your client, then mark it as sent.", [["#/seller/invoices/new", "New invoice", "green"], ["#/seller/customers", "Add a customer", "white"]]),
      };
    return {
      title: "Invoices",
      subtitle: "Every invoice, with its status in words.",
      action: `<a class="btn green" href="#/seller/invoices/new">New invoice</a>`,
      html: `<section class="panel">${rows.map((inv) => `<a class="list-row seller-row" href="#/seller/invoices/${enc(inv.id)}"><div><h3>${esc(inv.number)} · ${esc(inv.customer.name)}</h3><p>Due ${longDate(inv.due_date)}</p></div><div class="seller-row-end">${chip(inv)}<strong class="num">${rupee(inv.total_minor)}</strong>${inv.status !== "draft" && inv.balance_minor > 0 ? `<p>Balance ${rupee(inv.balance_minor)}</p>` : ""}</div></a>`).join("")}</section>`,
    };
  }

  function lineRow() {
    const n = ++lineSeq;
    return `<div class="seller-line"><div class="form-field"><label for="seller-desc-${n}">Description</label><input id="seller-desc-${n}" name="description" maxlength="200" autocomplete="off" required></div><div class="form-field"><label for="seller-qty-${n}">Quantity</label><input id="seller-qty-${n}" name="quantity" type="number" min="1" max="10000" step="1" value="1" required></div><div class="form-field"><label for="seller-price-${n}">Unit price (₹)</label><input id="seller-price-${n}" name="price" type="number" min="0.01" max="10000000" step="0.01" required></div><button type="button" class="btn small ghost" data-seller-action="remove-line">Remove line</button></div>`;
  }

  function updateTotal(form) {
    let total = 0;
    form.querySelectorAll(".seller-line").forEach((row) => {
      const qty = Number(row.querySelector('[name="quantity"]').value) || 0;
      const price = Number(row.querySelector('[name="price"]').value) || 0;
      total += qty * Math.round(price * 100);
    });
    const out = document.getElementById("seller-live-total");
    if (out) out.textContent = rupee(total);
  }

  async function invoiceNew(query) {
    const customers = await api("/seller/customers");
    if (!customers.length)
      return { title: "New invoice", back: "seller/invoices", backLabel: "Invoices",
        html: emptyState("Add a customer first", "An invoice needs a customer. Add one, then come back here.", [["#/seller/customers", "Add a customer", "green"]]) };
    const preselect = query.get("customer");
    const issue = todayIso();
    const options = customers.map((c) => `<option value="${esc(c.id)}" ${c.id === preselect ? "selected" : ""}>${esc(c.name)}</option>`).join("");
    return {
      title: "New invoice",
      subtitle: "Save a draft, share its details, then mark it as sent.",
      back: "seller/invoices", backLabel: "Invoices",
      html: `<form id="seller-invoice-form" class="panel seller-form">
        <p class="field-hint"><a href="#/knowledge/invoice-follow-ups">How invoices and payment follow-ups work</a></p>
        <div class="seller-two">
          <div class="form-field"><label for="seller-customer">Customer</label><select id="seller-customer" name="customer_id" required>${options}</select></div>
          <div class="form-field"><label for="seller-issue">Issue date</label><input id="seller-issue" name="issue_date" type="date" value="${issue}" required></div>
          <div class="form-field"><label for="seller-due">Due date</label><input id="seller-due" name="due_date" type="date" value="${shiftIso(issue, 15)}" required></div>
        </div>
        <fieldset class="seller-lines"><legend>Line items</legend><div id="seller-lines">${lineRow()}</div><button type="button" class="btn small white" data-seller-action="add-line">Add line item</button></fieldset>
        <p class="seller-total">Invoice total <strong id="seller-live-total">₹0</strong></p>
        <p id="seller-form-error" class="seller-error" role="alert" hidden></p>
        <div class="actions"><button type="submit" class="btn green">Save draft</button><a class="btn white" href="#/seller/invoices">Cancel</a></div>
      </form>`,
    };
  }

  function paymentForm(invoice) {
    const balance = invoice.balance_minor;
    return `<form id="seller-payment-form" class="panel seller-form" data-invoice-id="${esc(invoice.id)}" data-request-id="${crypto.randomUUID()}">
      <h2>Add a received payment</h2>
      <p class="field-hint">The client still owes ${rupee(balance)}. Add a payment here after you receive it.</p>
      <p class="field-hint"><a href="#/knowledge/partial-receipts">How to record a full or partial payment</a> · <a href="#/knowledge/receiving-upi">Receive UPI payments safely</a></p>
      <div class="seller-two">
        <div class="form-field"><label for="seller-pay-amount">Amount received (₹)</label><input id="seller-pay-amount" name="amount" type="number" min="0.01" max="${(balance / 100).toFixed(2)}" step="0.01" value="${(balance / 100).toFixed(2)}" required></div>
        <div class="form-field"><label for="seller-pay-method">Payment method</label><select id="seller-pay-method" name="method">${PAYMENT_METHODS.map(([k, l]) => `<option value="${k}">${esc(t(l))}</option>`).join("")}</select></div>
        <div class="form-field"><label for="seller-pay-ref">Payment reference (optional)</label><input id="seller-pay-ref" name="reference" maxlength="80" autocomplete="off"></div>
        <div class="form-field"><label for="seller-pay-date">Date received</label><input id="seller-pay-date" name="received_on" type="date" value="${todayIso()}" required></div>
      </div>
      <p id="seller-pay-error" class="seller-error" role="alert" hidden></p>
      <div class="actions"><button type="submit" class="btn green">Save payment</button></div>
    </form>`;
  }

  function upiQr(reminder) {
    if (typeof qrcode !== "function") return `<p class="field-hint">QR code unavailable. Use the UPI link in the reminder.</p>`;
    const qr = qrcode(0, "M");
    qr.addData(paymentLink({qr_token: reminder.upi_link}));
    qr.make();
    return qr.createImgTag(5, 12, "Open ContextIQ payment-code entry, then review the UPI request");
  }

  function reminderPanel(reminder, invoiceId) {
    const tone = (key, label) => `<button type="button" class="btn small ${reminder.tone === key ? "green" : "white"}" aria-pressed="${reminder.tone === key}" data-seller-action="set-tone" data-id="${esc(invoiceId)}" data-tone="${key}">${esc(t(label))}</button>`;
    return `<h2 id="seller-reminder-title">${esc(t("Payment reminder"))}</h2>
      <div class="seller-toggle-row" role="group" aria-label="Reminder tone">${tone("friendly", "Friendly")}${tone("firm", "Firm")}</div>
      <label for="seller-reminder-text">Message to your client</label>
      <p class="field-hint">Edit the message, then copy it or open WhatsApp to send it.</p>
      <textarea id="seller-reminder-text" class="seller-reminder-text" rows="12">${esc(reminder.text)}</textarea>
      <div class="actions"><button type="button" class="btn small green" data-seller-action="copy-reminder">Copy message</button><button type="button" class="btn small white" data-seller-action="copy-upi" data-id="${esc(invoiceId)}">Copy UPI payment link</button>${reminder.whatsapp_url ? `<a class="btn small white" href="${esc(reminder.whatsapp_url)}" target="_blank" rel="noopener">Open WhatsApp</a>` : ""}</div>`;
  }

  async function invoiceDetail(id) {
    const invoice = await api(`/seller/invoices/${enc(id)}`);
    const isOpen = ["sent", "part_paid"].includes(invoice.status) && invoice.balance_minor > 0;
    const canCancel = ["draft", "sent"].includes(invoice.status) && invoice.paid_minor === 0;
    let side = "";
    if (isOpen) {
      try {
        const reminder = await api(`/seller/invoices/${enc(id)}/reminder?tone=friendly`);
        side += `<section class="panel seller-qr-panel"><h2>${esc(t("Client payment QR"))}</h2><div class="seller-qr" role="img" aria-label="UPI QR for ${rupee(reminder.amount_minor)}">${upiQr(reminder)}</div><p class="field-hint">${reminder.demo_recipient ? "This QR uses a demo UPI ID. Add your UPI ID in Business settings before sharing it." : `Review recipient and amount in your UPI app before paying ${rupee(reminder.amount_minor)}.`}</p></section>`;
        side += `<section class="panel seller-reminder" aria-labelledby="seller-reminder-title"><div id="seller-reminder-panel">${reminderPanel(reminder, invoice.id)}</div></section>`;
      } catch (error) {
        side += `<section class="panel"><h2>${esc(t("Payment reminder"))}</h2><p class="seller-error" role="alert">${esc(error.message)}</p></section>`;
      }
    }
    const actions = [];
    actions.push(`<button type="button" class="btn white" data-seller-action="copy-invoice" data-id="${esc(invoice.id)}">Copy invoice</button>`);
    if (invoice.status === "draft") actions.push(`<button type="button" class="btn green" data-seller-action="send-invoice" data-id="${esc(invoice.id)}">Mark as sent</button>`);
    if (canCancel) actions.push(`<button type="button" class="btn white" data-seller-action="cancel-invoice" data-id="${esc(invoice.id)}">Cancel invoice</button>`);
    const lines = invoice.lines.map((l) => `<tr><td>${esc(l.description)}</td><td class="num">${l.quantity}</td><td class="num">${rupee(l.unit_price_minor)}</td><td class="num">${rupee(l.amount_minor)}</td></tr>`).join("");
    const payments = invoice.payments.length
      ? `<div class="table-wrap"><table class="seller-table"><caption>Payments received</caption><thead><tr><th scope="col">Date</th><th scope="col">Method</th><th scope="col">Reference</th><th scope="col" class="num">Amount</th></tr></thead><tbody>${invoice.payments.map((p) => `<tr><td>${longDate(p.received_on)}</td><td>${esc(METHOD_LABEL[p.method] || p.method)}</td><td>${esc(p.reference || "—")}</td><td class="num">${rupee(p.amount_minor)}</td></tr>`).join("")}</tbody></table></div>`
      : `<p class="field-hint">No payments recorded yet.</p>`;
    const dueNote = invoice.overdue ? `Overdue by ${invoice.days_overdue} days` : `Due ${longDate(invoice.due_date)}`;
    return {
      title: `Invoice ${invoice.number}`,
      subtitle: `${invoice.customer.name} · ${dueNote}`,
      back: "seller/invoices", backLabel: "Invoices",
      action: chip(invoice),
      html: `<div class="seller-two seller-detail">
        <div>
          <section class="panel"><div class="section-top"><h2>${esc(t("Lines"))}</h2></div><div class="table-wrap"><table class="seller-table"><thead><tr><th scope="col">Item</th><th scope="col" class="num">Qty</th><th scope="col" class="num">Rate</th><th scope="col" class="num">Amount</th></tr></thead><tbody>${lines}</tbody></table></div>
            <dl class="seller-totals"><div><dt>Total</dt><dd>${rupee(invoice.total_minor)}</dd></div><div><dt>Paid</dt><dd>${rupee(invoice.paid_minor)}</dd></div><div><dt>Balance</dt><dd><strong>${rupee(invoice.balance_minor)}</strong></dd></div></dl>
            ${actions.length ? `<div class="actions">${actions.join("")}</div>` : ""}
          </section>
          ${isOpen ? paymentForm(invoice) : ""}
          <section class="panel"><h2>${esc(t("Payments"))}</h2>${payments}</section>
        </div>
        <div>${side}</div>
      </div>`,
    };
  }

  async function invoicesView(query, id) {
    if (id === "new") return invoiceNew(query);
    if (id) return invoiceDetail(id);
    return invoicesList();
  }

  // ---------- customers ----------
  async function customersView() {
    const rows = await api("/seller/customers");
    const list = rows.length
      ? `<section class="panel">${rows.map((c) => `<div class="list-row seller-row"><div><h3>${esc(c.name)}</h3><p>${esc([c.phone, c.email].filter(Boolean).join(" · ") || "No contact details")}</p><p>${c.usual_payment_delay_days ? `Usually pays ${c.usual_payment_delay_days} days after due date` : "Usually pays on time"}</p></div><div class="seller-row-end"><p>Open balance</p><strong class="num">${rupee(c.outstanding_minor)}</strong><div class="actions"><a class="btn small white" href="#/seller/invoices/new?customer=${enc(c.id)}">New invoice</a><a class="btn small ghost" href="#/seller/forecast?customer=${enc(c.id)}">What if they pay late</a></div></div></div>`).join("")}</section>`
      : emptyState("No customers yet", "Add the people or businesses you invoice. Use the form below to add your first one.");
    const form = `<section class="panel seller-form"><h2>${esc(t("Add a customer"))}</h2><form id="seller-customer-form">
      <div class="seller-two">
        <div class="form-field"><label for="seller-cust-name">Name</label><input id="seller-cust-name" name="name" maxlength="120" required autocomplete="organization"></div>
        <div class="form-field"><label for="seller-cust-phone">Phone (optional)</label><input id="seller-cust-phone" name="phone" type="tel" maxlength="20" autocomplete="tel"></div>
        <div class="form-field"><label for="seller-cust-email">Email (optional)</label><input id="seller-cust-email" name="email" type="email" maxlength="120" autocomplete="email"></div>
        <div class="form-field"><label for="seller-cust-delay">Usual payment delay (days after due date)</label><input id="seller-cust-delay" name="usual_payment_delay_days" type="number" min="0" max="120" step="1" value="0" required><span class="field-hint">0 means they usually pay on time.</span></div>
      </div>
      <p id="seller-customer-error" class="seller-error" role="alert" hidden></p>
      <div class="actions"><button type="submit" class="btn green">Save customer</button></div></form></section>`;
    return {
      title: "Customers",
      subtitle: "Who you invoice, and how quickly they usually pay.",
      html: `${list}${form}`,
    };
  }

  // ---------- cash forecast ----------
  function forecastChart(series, label) {
    const model = chartModel(series);
    if (!model) return '<p class="field-hint">No forecast records available.</p>';
    series = model.rows;
    const W = 720, H = 260, L = 76, R = 12, T = 14, B = 30;
    const lo = model.min, hi = model.max;
    const x = (i) => L + (i * (W - L - R)) / Math.max(series.length - 1, 1);
    const y = (v) => T + ((hi - v) * (H - T - B)) / (hi - lo);
    const line = series.map((d, i) => `${i ? `${x(i).toFixed(1)},${y(series[i - 1].balance_minor).toFixed(1)} ` : ""}${x(i).toFixed(1)},${y(d.balance_minor).toFixed(1)}`).join(" ");
    const area = `${x(0).toFixed(1)},${(H - B).toFixed(1)} ${line} ${x(series.length - 1).toFixed(1)},${(H - B).toFixed(1)}`;
    const ticks = model.ticks;
    const grid = ticks.map((v) => `<line x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" class="grid"/><text x="${L - 8}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${esc(rupee(Math.round(v)))}</text>`).join("");
    const zero = lo <= 0 && hi >= 0 ? `<line x1="${L}" x2="${W - R}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" class="zero"/>` : "";
    const mid = Math.floor((series.length - 1) / 2);
    const xLabels = [0, mid, series.length - 1].map((i) => `<text x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="${i === 0 ? "start" : i === series.length - 1 ? "end" : "middle"}">${shortDate(series[i].date)}</text>`).join("");
    const firstNeg = series.findIndex((d) => d.balance_minor < 0);
    const marker = firstNeg >= 0 ? `<circle cx="${x(firstNeg).toFixed(1)}" cy="${y(series[firstNeg].balance_minor).toFixed(1)}" r="5" class="neg-dot"/>` : "";
    const inspection = series.map((d, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(d.balance_minor).toFixed(1)}" r="7" fill="transparent"><title>${esc(longDate(d.date))}: ${esc(rupee(d.balance_minor))}</title></circle>`).join("");
    return `<svg class="seller-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">${grid}${zero}<polygon points="${area}" class="area"/><polyline points="${line}" class="line"/>${marker}${xLabels}${inspection}</svg>`;
  }

  async function forecastView(query) {
    const [forecast, customers] = await Promise.all([api("/seller/forecast?horizon_days=90"), api("/seller/customers")]);
    const horizonParam = Number(query.get("days"));
    const horizon = [30, 60, 90].includes(horizonParam) ? horizonParam : 60;
    const series = forecast.days.slice(0, horizon); // the 90-day forecast; the first N days are identical to an N-day run
    const minDay = series.reduce((best, d) => (best === null || d.balance_minor < best.balance_minor ? d : best), null);
    const firstNeg = series.find((d) => d.balance_minor < 0);
    const receipts = series.reduce((sum, d) => sum + d.inflow_minor, 0);
    const bills = series.reduce((sum, d) => sum + d.outflow_minor, 0);
    const ending = series[series.length - 1].balance_minor;
    const custQ = query.get("customer") ? `&customer=${enc(query.get("customer"))}` : "";
    const warning = firstNeg
      ? `<div class="notice warn seller-warning" role="status"><strong>Cash goes negative on ${longDate(firstNeg.date)}.</strong> Chase overdue invoices or move bills before then.</div>`
      : `<div class="notice" role="status">Cash stays above zero for the next ${horizon} days. Lowest projected balance ${rupee(minDay.balance_minor)} on ${longDate(minDay.date)}.</div>`;
    const chips = [30, 60, 90].map((d) => `<a href="#/seller/forecast?days=${d}${custQ}" class="${d === horizon ? "active" : ""}" ${d === horizon ? 'aria-current="true"' : ""}>${d} days</a>`).join("");
    const preselect = query.get("customer");
    const options = `<option value="">All customers (delay applies to everyone)</option>${customers.map((c) => `<option value="${esc(c.id)}" ${c.id === preselect ? "selected" : ""}>${esc(c.name)}</option>`).join("")}`;
    const rows = series.map((d) => `<tr><td>${longDate(d.date)}</td><td class="num">${rupee(d.inflow_minor)}</td><td class="num">${rupee(d.outflow_minor)}</td><td class="num">${rupee(d.balance_minor)}</td></tr>`).join("");
    return {
      title: "Cash forecast",
      subtitle: `Projected balance over the next ${horizon} days, from open invoices and bills.`,
      html: `${warning}
        <div class="stat-row seller-stats">${stat("Opening balance", rupee(forecast.opening_minor))}${stat("Expected receipts", rupee(receipts), "positive")}${stat("Bills due", rupee(bills), "negative")}${stat(`Balance in ${horizon} days`, rupee(ending))}</div>
        <section class="panel"><div class="section-top"><h2>${esc(t("Projected balance"))}</h2><div class="seller-chips" role="group" aria-label="Forecast length">${chips}</div></div>
          ${forecastChart(series, `Projected balance for ${horizon} days, lowest ${rupee(minDay.balance_minor)}`)}
          <p class="field-hint">Lowest point ${rupee(minDay.balance_minor)} on ${longDate(minDay.date)}.</p>
          <p class="field-hint">Receipts use invoice due dates and each client's usual delay. Already overdue receipts are assumed today. Use the delay scenario to test what happens if collection takes longer.</p>
          <p class="field-hint"><a href="#/knowledge/cash-forecast">How this forecast is calculated</a></p>
          <details><summary>Day-by-day figures</summary><div class="table-wrap"><table class="seller-table"><caption>Projected balance by day</caption><thead><tr><th scope="col">Date</th><th scope="col" class="num">Receipts</th><th scope="col" class="num">Bills</th><th scope="col" class="num">Balance</th></tr></thead><tbody>${rows}</tbody></table></div></details>
        </section>
        <section class="panel seller-form" aria-labelledby="seller-whatif-title"><h2 id="seller-whatif-title">${esc(t("What if a client pays late?"))}</h2>
          <p class="field-hint">Move the selected client’s expected receipts 15 days later and compare the cash gap before taking action.</p>
          <form id="seller-whatif-form">
            <div class="seller-two">
              <div class="form-field"><label for="seller-whatif-customer">Client</label><select id="seller-whatif-customer" name="customer_id">${options}</select></div>
              <div class="form-field"><label for="seller-whatif-delay">Days later</label><input id="seller-whatif-delay" name="delay_days" type="number" min="0" max="120" step="1" value="15" required></div>
              <div class="form-field"><label for="seller-whatif-horizon">Look ahead</label><select id="seller-whatif-horizon" name="horizon_days"><option value="30">30 days</option><option value="60">60 days</option><option value="90">90 days</option></select></div>
            </div>
            <div class="actions"><button type="submit" class="btn green">Run what-if</button></div>
          </form>
          <div id="seller-whatif-result" aria-live="polite"></div>
        </section>`,
    };
  }

  // ---------- bills ----------
  async function billsView() {
    const rows = await api("/seller/bills");
    const recur = { none: "One-off", monthly: "Every month" };
    const list = rows.length
      ? `<section class="panel">${rows.map((b) => `<div class="list-row seller-row"><div><h3>${esc(b.name)}</h3><p>Due ${longDate(b.due_date)} · ${esc(recur[b.recurrence] || b.recurrence)}</p></div><div class="seller-row-end"><span class="seller-chip ${b.paid ? "paid" : "sent"}">${b.paid ? "Paid" : "Unpaid"}</span><strong class="num">${rupee(b.amount_minor)}</strong>${!b.paid ? `<div class="actions"><button class="btn small white" type="button" data-seller-action="pay-bill" data-id="${esc(b.id)}">Record paid</button><button class="btn small ghost" type="button" data-seller-action="move-bill" data-id="${esc(b.id)}">Change date</button></div>` : ""}</div></div>`).join("")}</section>`
      : emptyState("No bills yet", "Add rent, subscriptions and supplier payments so the cash forecast can account for them. Use the form below.");
    const form = `<section class="panel seller-form"><h2>${esc(t("Add a bill"))}</h2><form id="seller-bill-form">
      <div class="seller-two">
        <div class="form-field"><label for="seller-bill-name">Bill name</label><input id="seller-bill-name" name="name" maxlength="120" required></div>
        <div class="form-field"><label for="seller-bill-amount">Amount (₹)</label><input id="seller-bill-amount" name="amount" type="number" min="0.01" max="10000000" step="0.01" required></div>
        <div class="form-field"><label for="seller-bill-due">Due date</label><input id="seller-bill-due" name="due_date" type="date" value="${todayIso()}" required></div>
        <div class="form-field"><label for="seller-bill-recur">Repeats</label><select id="seller-bill-recur" name="recurrence"><option value="none">One-off</option><option value="monthly">Every month</option></select></div>
      </div>
      <p id="seller-bill-error" class="seller-error" role="alert" hidden></p>
      <div class="actions"><button type="submit" class="btn green">Save bill</button></div></form></section>`;
    return { title: "Bills", subtitle: "Payments you must make, so the forecast can plan for them.", html: `${list}${form}` };
  }

  // ---------- page dispatch ----------
  async function settingsView() {
    const cfg = await api("/seller/settings");
    return { title: "Business settings", subtitle: "Your collection details and starting cash.",
      html: `<form id="seller-settings-form" class="panel seller-form"><label for="seller-payee">Business name</label><input id="seller-payee" name="payee_name" value="${esc(cfg.payee_name)}" maxlength="60" required><label for="seller-upi">UPI address</label><input id="seller-upi" name="upi_vpa" value="${esc(cfg.upi_vpa)}" maxlength="80" required><label for="seller-opening">Starting cash before recorded receipts (₹)</label><input id="seller-opening" name="opening" type="number" step="0.01" value="${cfg.opening_balance_minor / 100}" required><p class="field-hint">Confirmed receipts add to starting cash. Recorded bill payments reduce it.</p><div class="actions"><button type="submit" class="btn green">Save settings</button></div></form>` };
  }

  const VIEWS = {
    settings: () => settingsView(),
    dashboard: (query) => dashboardView(query),
    invoices: (query, id) => invoicesView(query, id),
    customers: () => customersView(),
    forecast: (query) => forecastView(query),
    bills: () => billsView(),
  };

  async function sellerPage() {
    const section = S.route[1] || "dashboard";
    const view = VIEWS[section];
    if (!view) throw new Error("Page not found");
    const result = await view(routeQuery(), S.route[2]);
    const current = section === "dashboard" ? "seller" : `seller/${section}`;
    return `${result.back ? back(result.back, result.backLabel) : ""}${head(result.title, result.subtitle || "", result.action || "")}${sellerTabs(current)}<div class="seller-page">${result.html}</div>`;
  }

  // ---------- actions (clicks) ----------
  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      throw new Error("Copy failed. Select the text and copy it manually.");
    }
  }
  const ACTIONS = {
    "copy-upi": async (control) => {
      const reminder = await api(`/seller/invoices/${enc(control.dataset.id)}/reminder`);
      await copyText(reminder.upi_link);
      toast("UPI payment link copied");
    },
    "copy-invoice": async (control) => {
      const invoice = await api(`/seller/invoices/${enc(control.dataset.id)}`);
      await copyText(invoice.share_text);
      toast("Invoice copied. Review and share it with your client.");
    },
    "pay-bill": async (control) => {
      if (!window.confirm("Record this bill as paid from your business cash?")) return;
      control.disabled = true;
      control.dataset.requestId ||= crypto.randomUUID();
      try {
        await api(`/seller/bills/${enc(control.dataset.id)}/record-payment`, {
          confirmed: true, request_id: control.dataset.requestId,
        });
        toast("Bill payment recorded. Cash forecast updated.");
        await render();
      } finally {
        control.disabled = false;
      }
    },
    "move-bill": async (control) => {
      const rows = await api("/seller/bills");
      const bill = rows.find((row) => row.id === control.dataset.id);
      if (!bill) return;
      modal(`<h2>Change bill date</h2><p>${esc(bill.name)} · ${rupee(bill.amount_minor)}</p><form id="seller-move-bill-form" data-id="${esc(bill.id)}" data-name="${esc(bill.name)}" data-amount="${bill.amount_minor}" data-recurrence="${esc(bill.recurrence)}"><label for="seller-new-due">Agreed due date</label><input id="seller-new-due" name="due" type="date" value="${bill.due_date}" required><p class="field-hint">Use a date agreed with your supplier. The forecast updates when you save.</p><div class="actions"><button class="btn green" type="submit">Save date</button></div></form>`);
    },
    "add-line": async (control) => {
      const form = control.closest("form");
      document.getElementById("seller-lines").insertAdjacentHTML("beforeend", lineRow());
      updateTotal(form);
      const inputs = form.querySelectorAll('.seller-line [name="description"]');
      inputs[inputs.length - 1].focus();
    },
    "remove-line": async (control) => {
      const form = control.closest("form");
      if (document.querySelectorAll(".seller-line").length <= 1) return toast("An invoice needs at least one line.");
      control.closest(".seller-line").remove();
      updateTotal(form);
    },
    "send-invoice": async (control) => {
      await api(`/seller/invoices/${enc(control.dataset.id)}/send`, {});
      toast("Invoice marked as sent");
      render();
    },
    "cancel-invoice": async (control) => {
      if (!window.confirm("Cancel this invoice? A cancelled invoice cannot be reopened.")) return;
      await api(`/seller/invoices/${enc(control.dataset.id)}/cancel`, {});
      toast("Invoice cancelled");
      render();
    },
    "set-tone": async (control) => {
      const id = control.dataset.id;
      const reminder = await api(`/seller/invoices/${enc(id)}/reminder?tone=${enc(control.dataset.tone)}`);
      document.getElementById("seller-reminder-panel").innerHTML = reminderPanel(reminder, id);
    },
    "copy-reminder": async () => {
      await copyText(document.getElementById("seller-reminder-text").value);
      toast("Reminder copied");
    },
    "copy-alert": async (control) => {
      const item = lastAlerts[Number(control.dataset.id)];
      if (!item?.reminder) return toast("No reminder for this item.");
      await copyText(item.reminder.text);
      toast("Reminder copied");
    },
  };

  document.addEventListener("click", (event) => {
    const control = event.target.closest?.("[data-seller-action]");
    if (!control) return;
    event.preventDefault();
    const handler = ACTIONS[control.dataset.sellerAction];
    if (handler) handler(control).catch((error) => toast(error.message));
  });

  document.addEventListener("input", (event) => {
    if (event.target.form?.id === "seller-invoice-form") updateTotal(event.target.form);
    if (event.target.id === "seller-reminder-text") {
      const share = event.target.closest(".seller-reminder")?.querySelector('a[href^="https://wa.me/"]');
      if (share) {
        const url = new URL(share.href);
        url.searchParams.set("text", event.target.value);
        share.href = url.href;
      }
    }
  });

  // ---------- form submissions ----------
  function showError(id, message) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = message;
    el.hidden = !message;
  }

  const SUBMITS = {
    async "seller-settings-form"(form) {
      if (!form.reportValidity()) return;
      await api("/seller/settings", {
        upi_vpa: form.elements.upi_vpa.value.trim(),
        payee_name: form.elements.payee_name.value.trim(),
        opening_balance_minor: toPaise(form.elements.opening.value),
      }, "PUT");
      toast("Business settings saved");
      await render();
    },
    async "seller-move-bill-form"(form) {
      if (!form.reportValidity()) return;
      await api(`/seller/bills/${enc(form.dataset.id)}`, {
        name: form.dataset.name, amount_minor: Number(form.dataset.amount),
        recurrence: form.dataset.recurrence, due_date: form.elements.due.value,
      }, "PUT");
      closeModal();
      toast("Bill date updated");
      await render();
    },
    async "seller-invoice-form"(form) {
      const lines = [...form.querySelectorAll(".seller-line")].map((row) => ({
        description: row.querySelector('[name="description"]').value.trim(),
        quantity: Number(row.querySelector('[name="quantity"]').value),
        unit_price_minor: toPaise(row.querySelector('[name="price"]').value),
      }));
      const issue = form.elements.issue_date.value;
      const due = form.elements.due_date.value;
      let problem = "";
      if (!form.reportValidity()) problem = "Check the highlighted fields.";
      else if (lines.some((l) => !l.description || !Number.isInteger(l.quantity) || l.quantity < 1 || !(l.unit_price_minor > 0)))
        problem = "Each line needs a description, a whole-number quantity and a price above zero.";
      else if (due < issue) problem = "Due date cannot be before the issue date.";
      showError("seller-form-error", problem);
      if (problem) return;
      const invoice = await api("/seller/invoices", { customer_id: form.elements.customer_id.value, issue_date: issue, due_date: due, lines });
      toast("Draft saved");
      navigate(`seller/invoices/${invoice.id}`);
    },
    async "seller-payment-form"(form) {
      if (!form.reportValidity()) return;
      const id = form.dataset.invoiceId;
      try {
        await api(`/seller/invoices/${enc(id)}/payments`, {
          amount_minor: toPaise(form.elements.amount.value),
          method: form.elements.method.value,
          reference: form.elements.reference.value.trim(),
          received_on: form.elements.received_on.value,
          request_id: form.dataset.requestId,
        });
      } catch (error) {
        return showError("seller-pay-error", error.message);
      }
      toast("Payment recorded");
      render();
    },
    async "seller-customer-form"(form) {
      if (!form.reportValidity()) return;
      try {
        await api("/seller/customers", {
          name: form.elements.name.value.trim(),
          phone: form.elements.phone.value.trim(),
          email: form.elements.email.value.trim(),
          usual_payment_delay_days: Number(form.elements.usual_payment_delay_days.value),
        });
      } catch (error) {
        return showError("seller-customer-error", error.message);
      }
      toast("Customer saved");
      render();
    },
    async "seller-bill-form"(form) {
      if (!form.reportValidity()) return;
      try {
        await api("/seller/bills", {
          name: form.elements.name.value.trim(),
          amount_minor: toPaise(form.elements.amount.value),
          due_date: form.elements.due_date.value,
          recurrence: form.elements.recurrence.value,
        });
      } catch (error) {
        return showError("seller-bill-error", error.message);
      }
      toast("Bill saved");
      render();
    },
    async "seller-whatif-form"(form) {
      if (!form.reportValidity()) return;
      const target = document.getElementById("seller-whatif-result");
      const params = new URLSearchParams({ delay_days: form.elements.delay_days.value, horizon_days: form.elements.horizon_days.value });
      if (form.elements.customer_id.value) params.set("customer_id", form.elements.customer_id.value);
      try {
        const r = await api(`/seller/forecast/what-if?${params}`);
        const who = r.customer_name || "All customers";
        const change = r.change_in_min_balance_minor;
        const effect = change === 0
          ? "does not change the lowest projected balance"
          : `${change < 0 ? "lowers" : "raises"} the lowest projected balance by ${rupee(Math.abs(change))}`;
        target.innerHTML = `<div class="notice seller-whatif"><p><strong>${esc(who)}</strong> paying ${r.delay_days} days later ${esc(effect)}.</p>
          <div class="seller-two"><div><h3>Today's plan</h3><p>Lowest ${rupee(r.baseline.min_balance_minor)} on ${longDate(r.baseline.min_balance_date)}</p></div>
          <div><h3>With the delay</h3><p>Lowest ${rupee(r.scenario.min_balance_minor)} on ${longDate(r.scenario.min_balance_date)}</p>
          <p>${r.scenario.first_negative_date ? `<span class="negative">Goes negative on ${longDate(r.scenario.first_negative_date)}</span>` : "Stays above zero"}</p></div></div></div>`;
      } catch (error) {
        target.innerHTML = `<p class="seller-error" role="alert">${esc(error.message)}</p>`;
      }
    },
  };

  window.addEventListener(
    "submit",
    (event) => {
      const form = event.target;
      if (!(form instanceof HTMLFormElement) || !SUBMITS[form.id]) return;
      // Stop the global v2-actions submit handler from treating these as its own forms.
      event.preventDefault();
      event.stopImmediatePropagation();
      const submit = form.querySelector('button[type="submit"]');
      if (submit?.disabled) return;
      if (submit) submit.disabled = true;
      SUBMITS[form.id](form).catch((error) => toast(error.message)).finally(() => {
        if (submit) submit.disabled = false;
      });
    },
    true,
  );

  window.ContextIQSeller = { pages: { seller: sellerPage }, rupee };
  setInterval(() => {
    if (S.route[0] === "seller" && !document.hidden && !document.activeElement?.closest("form")) {
      queueWorkspaceRefresh();
    }
  }, 60000);
})();
