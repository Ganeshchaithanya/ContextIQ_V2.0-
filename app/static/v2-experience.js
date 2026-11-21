"use strict";

function dashboardEndpoint() {
  return `/dashboard?days=${[7, 30, 90].includes(S.chartDays) ? S.chartDays : 30}`;
}

function chartModel(points) {
  const rows = points.filter((row) => Number.isSafeInteger(row.balance_minor) && /^\d{4}-\d{2}-\d{2}$/.test(row.date)
    && Number.isFinite(Date.parse(row.date)) && new Date(row.date).toISOString().slice(0, 10) === row.date)
    .map((row) => ({...row})).sort((a, b) => a.date.localeCompare(b.date));
  if (!rows.length) return null;
  const values = rows.map((row) => row.balance_minor), low = Math.min(...values), high = Math.max(...values);
  const padding = Math.max((high - low) * 0.15, Math.abs(high) * 0.015, 10000);
  const desired = (high - low + padding * 2) / 4;
  const base = 10 ** Math.floor(Math.log10(desired));
  const step = [1, 2, 5, 10].map((value) => value * base).find((value) => value >= desired);
  const min = low >= 0 ? Math.max(0, Math.floor((low - padding) / step) * step) : Math.floor((low - padding) / step) * step;
  const max = Math.max(min + step, Math.ceil((high + padding) / step) * step);
  return {rows, min, max, step, ticks: Array.from({length: Math.round((max - min) / step) + 1}, (_, i) => min + i * step)};
}

function drawChart(id, points) {
  const canvas = document.getElementById(id), model = chartModel(points);
  if (!canvas || !model) return;
  const {rows, min, max, ticks} = model;
  const width = canvas.parentElement.getBoundingClientRect().width;
  if (width < 120) return;
  const height = 245, ratio = Math.min(window.devicePixelRatio || 1, 3);
  canvas.width = width * ratio; canvas.height = height * ratio;
  canvas.style.height = `${height}px`; canvas.tabIndex = 0;
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  const left = 68, right = 15, top = 18, bottom = 35;
  const x = i => rows.length === 1 ? (left + width - right) / 2 : left + i * (width - left - right) / (rows.length - 1);
  const y = value => top + (max - value) * (height - top - bottom) / (max - min);
  let selected = rows.length - 1;
  const tooltip = canvas.nextElementSibling;
  const compact = value => new Intl.NumberFormat("en-IN", {style: "currency", currency: "INR", notation: "compact", maximumFractionDigits: 1}).format(value / 100);
  function paint(index = null) {
    ctx.clearRect(0, 0, width, height);
    ctx.font = "11px 'DM Sans', sans-serif"; ctx.textAlign = "left";
    for (const value of ticks) {
      ctx.strokeStyle = value === 0 ? "#b4c3aa" : "#e3e9dc";
      ctx.setLineDash(value === 0 ? [] : [3, 5]); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(left, y(value)); ctx.lineTo(width - right, y(value)); ctx.stroke();
      ctx.fillStyle = "#67735f"; ctx.fillText(compact(value), 0, y(value) + 4);
    }
    ctx.setLineDash([]);
    const labels = [...new Set([0, Math.floor((rows.length - 1) / 2), rows.length - 1])];
    for (const i of labels) {
      ctx.textAlign = i === rows.length - 1 ? "right" : i === 0 ? "left" : "center";
      ctx.fillText(date(rows[i].date), x(i), height - 8);
    }
    function line() {
      ctx.moveTo(x(0), y(rows[0].balance_minor));
      for (let i = 1; i < rows.length; i++) {
        ctx.lineTo(x(i), y(rows[i - 1].balance_minor));
        ctx.lineTo(x(i), y(rows[i].balance_minor));
      }
    }
    const gradient = ctx.createLinearGradient(0, top, 0, height - bottom);
    gradient.addColorStop(0, "#a8e63d50"); gradient.addColorStop(1, "#a8e63d04");
    ctx.beginPath(); line(); ctx.lineTo(x(rows.length - 1), height - bottom); ctx.lineTo(x(0), height - bottom);
    ctx.closePath(); ctx.fillStyle = gradient; ctx.fill();
    ctx.beginPath(); line(); ctx.lineWidth = 2.5; ctx.lineJoin = "round"; ctx.strokeStyle = "#527c27"; ctx.stroke();
    const last = index === null ? rows.length - 1 : index;
    if (index !== null) {
      ctx.setLineDash([3, 4]); ctx.strokeStyle = "#6b805d"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x(index), top); ctx.lineTo(x(index), height - bottom); ctx.stroke(); ctx.setLineDash([]);
    }
    ctx.beginPath(); ctx.arc(x(last), y(rows[last].balance_minor), 5, 0, Math.PI * 2);
    ctx.fillStyle = "#527c27"; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = "#fff"; ctx.stroke();
  }
  function inspect(index, announce = false) {
    selected = Math.max(0, Math.min(rows.length - 1, index));
    const row = rows[selected];
    paint(selected);
    if (tooltip) {
      tooltip.style.display = "block";
      tooltip.style.left = `${Math.max(0, Math.min(width - Math.min(240, width), x(selected) - 90))}px`;
      tooltip.style.top = "0px";
      tooltip.textContent = `${date(row.date)} · ${money(row.balance_minor)}${row.income_minor !== undefined ? `\nIn ${money(row.income_minor)} · Out ${money(row.expense_minor)}` : ""}`;
    }
    if (announce) canvas.setAttribute("aria-label", `${date(row.date)}: ${money(row.balance_minor)}. Use arrow keys to inspect daily values.`);
  }
  canvas.onpointermove = event => inspect(Math.round((event.clientX - canvas.getBoundingClientRect().left - left) / (width - left - right) * (rows.length - 1)));
  canvas.onpointerleave = () => { if (tooltip) tooltip.style.display = "none"; paint(); };
  canvas.onfocus = () => inspect(selected, true);
  canvas.onblur = canvas.onpointerleave;
  canvas.onkeydown = event => {
    const index = {ArrowLeft: selected - 1, ArrowRight: selected + 1, Home: 0, End: rows.length - 1}[event.key];
    if (index === undefined) return;
    event.preventDefault(); inspect(index, true);
  };
  paint();
}

function balanceChartCard(data) {
  const f = data.finance, days = S.chartDays || 30, change = f.balance_minor - f.opening_minor;
  return `<section class="chart-card financial-chart"><div class="section-top"><div><p class="chart-eyebrow">RECORDED CASH · INR</p><h3>Balance over time</h3></div><div class="chart-periods" role="group" aria-label="Chart period">${[7, 30, 90].map(value => `<button type="button" data-chart-days="${value}" aria-pressed="${days === value}">${value}D</button>`).join("")}</div></div><div class="chart-summary"><strong>${money(f.balance_minor)}</strong><span class="${change < 0 ? "negative" : "positive"}">${change < 0 ? "−" : "+"}${money(Math.abs(change))} over ${days} days</span></div><div class="chart-wrap"><canvas id="balance-chart" role="img" aria-label="Daily closing cash from the recorded ledger. Use arrow keys to inspect values."></canvas><span class="chart-tip"></span></div><p class="chart-basis"><i aria-hidden="true"></i>Daily closing balance. Flat days mean no recorded movement.</p><div class="reconciliation">${money(f.opening_minor)} opening + ${money(f.income_minor)} in − ${money(f.expense_minor)} out = <strong>${money(f.balance_minor)}</strong></div><details class="chart-records"><summary>Inspect the daily figures</summary><div class="chart-table-wrap"><table><thead><tr><th>Date</th><th>Money in</th><th>Money out</th><th>Closing balance</th></tr></thead><tbody>${f.chart.map(row => `<tr><td>${esc(date(row.date))}</td><td>${money(row.income_minor || 0)}</td><td>${money(row.expense_minor || 0)}</td><td>${money(row.balance_minor)}</td></tr>`).join("")}</tbody></table></div></details></section>`;
}

function aiImpact(data) {
  const a = data.allocation, priorities = data.suggestions.filter(row => !row.completed).length;
  return `<section class="ai-impact" aria-label="Tara's contribution"><div class="ai-impact-heading"><span aria-hidden="true">✦</span><div><h2>Tara connects the dots</h2><p>Updated from your records. Your decisions stay yours.</p></div><a href="#/transparency">AI &amp; privacy ↗</a></div><div class="ai-impact-figures"><a href="#/budget/allocation"><strong>${money(a.committed_minor + a.reserved_minor + a.savings_minor)}</strong><span>planned for bills, reserves &amp; savings</span></a><a href="#/home"><strong>${priorities}</strong><span>remaining priorities, ordered by urgency</span></a><a href="#/ask"><strong>Show the evidence</strong><span>answers with calculations and source records</span></a></div><p class="ai-impact-note">Planning reserves do not move money. Payment always needs your approval.</p></section>`;
}

async function transparencyPage() {
  const data = await api("/transparency"), i = data.impact;
  S.transparency = data;
  const model = data.model_questions_enabled && data.model_available;
  const routing = {llm: "Language model used to identify the question's topic", rules: "Topic identified by application rules", reviewed_guide: "Answer from a reviewed knowledge guide"};
  return `${head("AI & Privacy", "See the work. Check the evidence. Stay in control.")}${data.storage?.ephemeral ? '<div class="notice warn">SQLite demo storage: records and sessions can reset when the free server restarts or redeploys. Use fictional data and start a fresh demo afterward.</div>' : ""}<section class="transparency-hero"><span class="eyebrow">TARA · YOUR FINANCIAL GUIDE</span><h2>Connected planning.<br>Visible decisions.</h2><p>Tara prioritizes work and explains your records. Financial calculations run in the application, and payments require your confirmation.</p><div class="actions">${link("Ask Tara", "ask", "green")}<button class="btn white" type="button" data-guide-start>Replay visual tour</button></div></section><div class="grid two"><section class="panel"><h2>What is working for you</h2>${kv("Open commitments", money(i.committed_minor))}${kv("Manual reserves", money(i.reserved_minor))}${kv("Planned savings", money(i.savings_minor))}${kv("Available to spend", money(i.flexible_minor))}${kv("Remaining priorities", i.priorities)}${kv("Active price watches", i.active_watches)}${kv("Saved analyses", i.saved_analyses)}<p class="field-hint">These are current recorded figures, not estimated time saved or money already transferred.</p><div class="actions">${link("Check allocation", "budget/allocation", "small white")}${link("Open tracked products", "purchases/before", "small white")}</div></section><section class="panel" id="privacy-controls"><h2>Your cloud AI choice</h2><p class="privacy-state">${model ? "Cloud topic understanding is available" : "Record-based assistance is active"}</p><p>Known questions use application rules and recorded facts. For an unfamiliar question, enabling cloud AI allows its text to be sent to ${esc(data.provider || "the configured model provider")} to identify the topic. Amounts and payment authorization are calculated and checked by the application.</p><form id="privacy-form">${check("Use cloud AI to understand unfamiliar questions", "allow_model_questions", data.model_questions_enabled)}<button class="btn green small" type="submit">Save AI choice</button></form><p class="field-hint">Turning this off keeps budgets, reminders, the visual guide and record-backed answers available. Generic guide hints may still use a model with predefined wording and task type, without your question or financial amounts.</p></section></div><section class="panel"><h2>Where your information goes</h2><div class="privacy-explainer"><div><h3>Your private workspace</h3><p>Records use ${esc(data.storage?.engine || "the configured database")} on the hosted backend. Ownership checks isolate each workspace. They do not stay only on your phone.</p></div><div><h3>External services</h3><p>Public product pages are fetched for price tracking. Unfamiliar question text can reach the configured model when enabled. This screen never displays provider keys or session tokens.</p></div><div><h3>Your final approval</h3><p>Tara cannot approve a payment through chat. Review the exact invoice, amount and recipient on the payment screen. The current payment flows are simulated.</p></div></div></section><section class="panel"><h2>Observable activity</h2>${data.last_analysis ? `<p>${esc(routing[data.last_analysis.routing] || "Recorded analysis")}. Last completed ${esc(new Date(data.last_analysis.at).toLocaleString())}.</p><p class="field-hint">Analysis reference ${esc(data.last_analysis.run_id)}</p>${link("View answers and evidence", "ask", "small white")}` : '<p>No completed analysis yet. Ask Tara a question to create a saved answer with evidence.</p>'}<p class="field-hint">Worker last checked in: ${data.worker.last_heartbeat ? esc(new Date(data.worker.last_heartbeat).toLocaleString()) : "not recorded"}. Free web hosting can sleep; checks resume when the service wakes. Continuous background monitoring needs an always-on worker.</p><p class="field-hint">Snapshot ${esc(new Date(data.as_of).toLocaleString())} · ${esc(data.workspace)} workspace.</p></section>`;
}

function scanDraft(hash = location.hash) {
  const value = new URLSearchParams(hash.split("?")[1] || "").get("code") || "";
  return value.length <= 10000 ? value : "";
}

function paymentLink(row) {
  if (row.payment_url) return row.payment_url;
  return `${location.origin}/#/scan?code=${encodeURIComponent(row.qr_token)}`;
}

document.addEventListener("click", event => {
  const target = event.target.closest("[data-chart-days]");
  if (!target) return;
  const days = Number(target.dataset.chartDays);
  if (![7, 30, 90].includes(days) || days === (S.chartDays || 30)) return;
  S.chartDays = days;
  void guarded(render);
});
