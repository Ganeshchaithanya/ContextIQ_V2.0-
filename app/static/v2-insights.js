"use strict";

function paymentEntryLink(row) {
  return `${location.origin}/#/scan?code=${encodeURIComponent(row.qr_code || row.qr_token)}`;
}

function chartPeriodControls() {
  return `<div class="chart-controls" role="group" aria-label="Balance chart period">${[7, 30, 90].map(days => `<button type="button" data-chart-days="${days}" aria-pressed="${(S.chartDays || 30) === days}">${days}D</button>`).join("")}<span><i aria-hidden="true"></i> Recorded balance</span></div>`;
}

function automationWidgets(data) {
  const a = data.automation_summary;
  if (!a) return "";
  const checked = a.last_workspace_check_at ? new Date(a.last_workspace_check_at).toLocaleString("en-IN") : "Waiting for this workspace’s first scheduled check";
  return `<div class="intelligence-grid" data-automation-widgets><section class="intelligence-widget"><div class="widget-heading"><span class="widget-icon" aria-hidden="true">✦</span><div><p class="eyebrow">Working with your records</p><h2>Tara + connected systems</h2></div><span class="subtle-badge">${a.scheduled_checks_available ? "Checks available" : "Checks paused"}</span></div><div class="intelligence-metrics"><a href="#/budget/allocation"><strong>${a.open_commitments}</strong><span>commitments in your budget</span></a><a href="#/purchases/before"><strong>${a.tracked_products}</strong><span>products being tracked</span></a><a href="#/ask"><strong>${a.completed_analyses}</strong><span>saved explanations</span></a></div><p class="widget-proof">${money(a.savings_minor)} planned across ${a.savings_plans} savings ${a.savings_plans === 1 ? "goal" : "goals"}. Your budget recalculates from recorded money, bills and plans.</p><details><summary>See the difference &amp; evidence</summary><p>Budget arithmetic and alerts use server-side rules. Tara explains the records and can use the configured AI provider to understand questions. An AI suggestion never approves a payment.</p><p>Last scheduled workspace check: ${esc(checked)}.</p><p>${esc(a.basis)}</p><div class="actions"><a href="#/ask" class="answer-source-link">Open Tara’s explanations ↗</a><a href="#/budget/allocation" class="answer-source-link">Check the allocation ↗</a></div><p class="field-hint">Scheduled work runs while the free backend is awake. Price lows mean the lowest observed since tracking began.</p></details></section><section class="privacy-widget" data-privacy-widget><div class="widget-heading"><span class="widget-icon" aria-hidden="true"><svg width="20" height="22" viewBox="0 0 20 22" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="9" width="14" height="11" rx="3"/><path d="M6 9V6a4 4 0 0 1 8 0v3"/><path d="M10 13v3"/></svg></span><div><p class="eyebrow">Data &amp; control</p><h2>Your decisions stay yours</h2></div></div><ul class="privacy-promises"><li><span aria-hidden="true">✓</span> Private workspace · other demo users cannot view your records</li><li><span aria-hidden="true">✓</span> You review and approve payments and client messages</li><li><span aria-hidden="true">✓</span> Answers link back to their records and assumptions</li></ul><details><summary>What is shared and what you control</summary><p>${a.model_configured ? "An AI provider is configured. Your question may be sent to it for topic understanding; some merchant-text extraction can also use AI. Payment authorization stays behind server-side policy." : "No AI provider is configured. Recorded facts and rule-based answers remain available."}</p><p>Context signals: <strong>${a.context_enabled ? "enabled" : "off"}</strong>. Browser voice features: <strong>${a.voice_enabled ? "enabled" : "off"}</strong>. Voice processing depends on your browser and its provider.</p><p>This is a fictional-data demonstration, not a bank account. A QR link opens a review screen and does not grant wallet access.</p><a class="answer-source-link" href="#/preferences">Review your preferences ↗</a></details><a class="widget-footer-link" href="#/knowledge">Read the payment and privacy guides ↗</a></section></div>`;
}

document.addEventListener("click", event => {
  const choice = event.target.closest("[data-chart-days]");
  if (!choice || S.busy) return;
  const days = Number(choice.dataset.chartDays);
  if (![7, 30, 90].includes(days)) return;
  guarded(async () => { S.chartDays = days; await render(); });
});
