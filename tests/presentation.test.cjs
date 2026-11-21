const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = name => fs.readFileSync(path.join(__dirname, '../app/static', name), 'utf8');
function charts(extra = {}) {
  const ctx = vm.createContext({console, ...extra});
  vm.runInContext(source('v2-charts.js'), ctx);
  return points => { ctx.input = points; return vm.runInContext('balanceChartModel(input, 390, 230)', ctx); };
}
test('chart preserves exact values, dates, gaps, negatives and a meaningful scale', () => {
  const model = charts()([{date:'2026-11-21', balance_minor:-100}, {date:'2026-11-01', balance_minor:500000}, {date:'2026-11-02', balance_minor:500000}]);
  assert.equal(model.points.length, 3);
  assert.equal(model.points[2].balance_minor, -100);
  assert(model.min < -100 && model.max > 500000);
  assert(model.x(2) - model.x(1) > 18 * (model.x(1) - model.x(0)));
  assert(model.y(-100) > model.y(500000));
});
test('flat, single day, empty and malformed chart data stay safe and honest', () => {
  const make = charts();
  for (const balance_minor of [0, -90000, 900000000000]) {
    const model = make([{date:'2026-11-21', balance_minor}]);
    assert.equal(model.points.length, 1);
    assert(Number.isFinite(model.y(balance_minor)));
    assert.equal(model.x(0), 218);
  }
  assert.equal(make([]), null);
  assert.equal(make([null, {date:'2026-02-30', balance_minor:1}, {date:'bad', balance_minor:0}, {date:'2026-11-21', balance_minor:NaN}]), null);
});
test('chart keyboard and pointer inspection expose exact source amounts', () => {
  const attrs = {}, tooltip = {style:{}}, drawing = new Proxy({createLinearGradient:()=>({addColorStop(){}})}, {get:(obj,key)=>obj[key] || (()=>{})});
  const canvas = {parentElement:{getBoundingClientRect:()=>({width:390,height:230})}, nextElementSibling:tooltip, getContext:()=>drawing, setAttribute:(k,v)=>attrs[k]=v, getBoundingClientRect:()=>({left:0})};
  const ctx = vm.createContext({document:{getElementById:()=>canvas},window:{devicePixelRatio:2}, money:n=>`INR ${n/100}`});
  vm.runInContext(source('v2-charts.js'),ctx);
  vm.runInContext(`drawChart('balance-chart', [{date:'2026-11-20', balance_minor:10000},{date:'2026-11-21',balance_minor:9701}])`,ctx);
  canvas.onfocus();
  assert.match(tooltip.textContent,/97.01/);
  canvas.onkeydown({key:'Home',preventDefault(){}});
  assert.match(tooltip.textContent,/INR 100/);
  canvas.onpointerdown({clientX:380});
  assert.match(attrs['aria-label'],/97.01.*recorded/);
  canvas.onpointerleave();
  assert.equal(tooltip.style.display,'none');
});
test('QR link uses compact code on the current HTTPS origin', () => {
  const ctx = vm.createContext({location:{origin:'https://context-iq-v2-0.vercel.app'},document:{addEventListener(){}}});
  vm.runInContext(source('v2-insights.js'), ctx);
  const link = vm.runInContext(`paymentEntryLink({qr_code:'ciqr1.abc.def',qr_token:'legacy-long'})`,ctx);
  assert.equal(link, 'https://context-iq-v2-0.vercel.app/#/scan?code=ciqr1.abc.def');
});
test('QR arrival opens code entry before auth, escapes input and clears URL code', async () => {
  const app = {}, changes = [], S = {csrf:null, scanDraft:''};
  const ctx = vm.createContext({S, document:{addEventListener(){}}, location:{hash:'#/scan?code='+encodeURIComponent('<script>bad</script>'),pathname:'/'},history:{replaceState:(...args)=>changes.push(args)},URLSearchParams, guide:{clear(){}},stopCamera(){},$:()=>app,scanPage:()=>`<textarea>${S.scanDraft.replaceAll('<','&lt;')}</textarea>`,welcome:()=>{throw Error('wrong page');}});
  vm.runInContext(source('v2-pages.js'),ctx);
  await vm.runInContext('render()',ctx);
  assert.match(app.innerHTML,/payment-entry/);
  assert.match(app.innerHTML,/&lt;script>/);
  assert.equal(changes[0][2],'#/scan');
  assert.equal(S.scanDraft,'<script>bad</script>');
});
