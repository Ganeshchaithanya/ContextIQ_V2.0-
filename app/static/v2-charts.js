"use strict";

// Plot recorded day-end values, with no fabricated smoothing or transactions.
function balanceChartModel(points, width, height) {
  const clean = (Array.isArray(points) ? points : []).filter(point => point && Number.isSafeInteger(point.balance_minor) && /^\d{4}-\d{2}-\d{2}$/.test(point.date) && Number.isFinite(Date.parse(point.date)) && new Date(point.date + "T12:00:00Z").toISOString().slice(0, 10) === point.date)
    .slice().sort((a, b) => a.date.localeCompare(b.date));
  if (!clean.length || width < 100 || height < 80) return null;
  const values = clean.map(point => point.balance_minor);
  const low = Math.min(...values), high = Math.max(...values);
  const padding = Math.max((high - low) * 0.18, 10000);
  const rough = (high - low + padding * 2) / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].find(value => value * power >= rough) * power;
  const min = Math.floor((low - padding) / step) * step;
  const max = Math.ceil((high + padding) / step) * step;
  const left = width < 400 ? 64 : 76, right = 18, top = 20, bottom = 34;
  const stamps = clean.map(point => Date.parse(point.date + "T12:00:00Z"));
  const first = stamps[0], last = stamps[stamps.length - 1];
  const x = i => last === first ? (left + width - right) / 2 : left + (stamps[i] - first) / (last - first) * (width - left - right);
  const y = value => top + (max - value) / (max - min) * (height - top - bottom);
  const ticks = [];
  for (let value = min; value <= max + step / 100; value += step) ticks.push({value, y: y(value)});
  return {points: clean, min, max, ticks, left, right, top, bottom, width, height, x, y};
}

function drawChart(id, source) {
  const canvas = document.getElementById(id);
  if (!canvas) return;
  const bounds = canvas.parentElement.getBoundingClientRect();
  const ratio = Math.min(window.devicePixelRatio || 1, 3);
  canvas.width = Math.round(bounds.width * ratio);
  canvas.height = Math.round(bounds.height * ratio);
  const ctx = canvas.getContext("2d"), tooltip = canvas.nextElementSibling;
  if (!ctx) return;
  ctx.scale(ratio, ratio);
  const model = balanceChartModel(source, bounds.width, bounds.height);
  if (!model) {
    canvas.setAttribute("aria-label", "No recorded balance values in this range");
    if (tooltip) tooltip.style.display = "none";
    return;
  }
  const {points, left, right, top, bottom, width, height, x, y} = model;
  const future = id === "forecast-chart";
  const axisMoney = value => new Intl.NumberFormat("en-IN", {style: "currency", currency: "INR", notation: "compact", maximumFractionDigits: 1}).format(value / 100);
  const dayLabel = value => new Date(value + "T12:00:00Z").toLocaleDateString("en-IN", {day: "numeric", month: "short", timeZone: "Asia/Kolkata"});
  function path() {
    ctx.moveTo(x(0), y(points[0].balance_minor));
    for (let i = 1; i < points.length; i++) {
      ctx.lineTo(x(i), y(points[i - 1].balance_minor));
      ctx.lineTo(x(i), y(points[i].balance_minor));
    }
  }
  function paint(selected = null) {
    ctx.clearRect(0, 0, width, height);
    ctx.font = '11px -apple-system, BlinkMacSystemFont, "DM Sans", sans-serif';
    ctx.textAlign = "left";
    ctx.setLineDash([]);
    for (const tick of model.ticks) {
      ctx.strokeStyle = tick.value === 0 ? "#a6b8a5" : "#98afbd26";
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(left, tick.y); ctx.lineTo(width - right, tick.y); ctx.stroke();
      ctx.fillStyle = "#647584";
      ctx.fillText(axisMoney(tick.value), 0, tick.y + 4);
    }
    const labels = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
    for (const i of labels) {
      ctx.textAlign = i === points.length - 1 ? "right" : "left";
      ctx.fillText(dayLabel(points[i].date), x(i), height - 9);
    }
    const fill = ctx.createLinearGradient(0, top, 0, height - bottom);
    fill.addColorStop(0, "#88be6b40"); fill.addColorStop(1, "#88be6b02");
    ctx.beginPath(); path();
    ctx.lineTo(x(points.length - 1), height - bottom); ctx.lineTo(x(0), height - bottom); ctx.closePath();
    ctx.fillStyle = fill; ctx.fill();
    ctx.beginPath(); path(); ctx.strokeStyle = "#4b8246"; ctx.lineWidth = 2.5; ctx.lineJoin = "round";
    ctx.setLineDash(future ? [6, 4] : []); ctx.stroke(); ctx.setLineDash([]);
    points.forEach((point, i) => {
      if (i !== points.length - 1 && (i === 0 || point.balance_minor === points[i - 1].balance_minor)) return;
      ctx.beginPath(); ctx.arc(x(i), y(point.balance_minor), i === points.length - 1 ? 4 : 2.5, 0, Math.PI * 2);
      ctx.fillStyle = "#4b8246"; ctx.fill();
    });
    if (selected !== null) {
      ctx.beginPath(); ctx.moveTo(x(selected), top); ctx.lineTo(x(selected), height - bottom);
      ctx.strokeStyle = "#425e7866"; ctx.setLineDash([3, 4]); ctx.lineWidth = 1; ctx.stroke(); ctx.setLineDash([]);
      ctx.beginPath(); ctx.arc(x(selected), y(points[selected].balance_minor), 5, 0, Math.PI * 2);
      ctx.fillStyle = "#315c36"; ctx.fill();
    }
  }
  let selected = points.length - 1;
  function inspect(index) {
    selected = Math.max(0, Math.min(points.length - 1, index));
    paint(selected);
    const point = points[selected];
    const text = `${dayLabel(point.date)} · ${money(point.balance_minor)}${future ? " · projected" : " · recorded"}`;
    canvas.setAttribute("aria-label", text + ". Arrow keys change the day.");
    if (tooltip) {
      tooltip.style.display = "block"; tooltip.style.left = `${Math.max(0, Math.min(width - 220, x(selected) - 95))}px`;
      tooltip.style.top = "0px"; tooltip.textContent = text;
    }
  }
  canvas.onpointermove = canvas.onpointerdown = event => {
    const offset = event.clientX - canvas.getBoundingClientRect().left;
    const index = points.reduce((nearest, _, i) => Math.abs(x(i) - offset) < Math.abs(x(nearest) - offset) ? i : nearest, 0);
    inspect(index);
  };
  canvas.onpointerleave = () => { paint(); if (tooltip) tooltip.style.display = "none"; };
  canvas.onfocus = () => inspect(selected);
  canvas.onblur = canvas.onpointerleave;
  canvas.onkeydown = event => {
    const index = {ArrowLeft: selected - 1, ArrowRight: selected + 1, Home: 0, End: points.length - 1}[event.key];
    if (index === undefined) return;
    event.preventDefault(); inspect(index);
  };
  canvas.setAttribute("aria-label", `${future ? "Projected" : "Recorded"} day-end balances, ${points.length} days. Latest ${money(points[selected].balance_minor)}. Use arrow keys for exact values.`);
  paint();
}
