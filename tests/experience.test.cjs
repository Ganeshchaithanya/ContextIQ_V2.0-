const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup(hash = '#/home') {
  const app = {innerHTML: '', addEventListener() {}}, events = new Map();
  const context = {console, URLSearchParams, Intl, Date, location: {hash, origin: 'https://contextiq.example', pathname: '/'},
    window: {CIQ_LOCALES: {}, devicePixelRatio: 2, addEventListener() {}}, setInterval() {},
    document: {addEventListener(name, cb) {events.set(name, cb);}, querySelector() {return app;}, getElementById() {return null;}},
    navigator: {}, localStorage: {getItem() {return null;}},
    guide: {clear() {}, update() {context.guided = true;}}, stopCamera() {},
  };
  vm.createContext(context);
  for (const file of ['v2.js', 'v2-experience.js', 'v2-pages.js']) vm.runInContext(fs.readFileSync(`app/static/${file}`, 'utf8'), context);
  return {context, app, events, run: source => vm.runInContext(source, context)};
}

test('chart bounds cover positive, negative, flat, zero and single-point ledgers without invented records', () => {
  const app = setup();
  for (const values of [[0], [100, 100], [-100, -300], [-300, 600], [999999999, 999999998]]) {
    app.context.points = values.map((balance_minor, i) => ({date: `2026-11-${String(i + 1).padStart(2, '0')}`, balance_minor}));
    const model = app.run('chartModel(points)');
    assert.equal(model.rows.length, values.length);
    assert(model.min <= Math.min(...values));
    assert(model.max >= Math.max(...values));
    assert(model.max > model.min && model.step > 0);
    assert.deepEqual(Array.from(model.rows, row => row.balance_minor), values);
  }
  assert.equal(app.run('chartModel([])'), null);
  assert.equal(app.run('chartModel([{date:"2026-02-31",balance_minor:0},{date:"oops",balance_minor:0},{date:"2026-11-01",balance_minor:NaN}])'), null);
});

test('QR opens the anonymous code-entry screen with escaped data and active Tara', async () => {
  const app = setup('#/scan?code=' + encodeURIComponent('</textarea><script>alert(1)</script>'));
  await app.run('render()');
  assert.match(app.app.innerHTML, /id="token"/);
  assert.match(app.app.innerHTML, /&lt;\/textarea&gt;/);
  assert.doesNotMatch(app.app.innerHTML, /<script>/);
  assert.match(app.app.innerHTML, /does not sign you in or authorize/);
  assert.equal(app.context.guided, true);
  assert.equal(app.run('scanDraft("#/scan?code=" + "x".repeat(10001))'), '');
});

test('chart supports exact inspection with keyboard and pointer', () => {
  const app = setup(), attrs = {}, tip = {style: {}};
  const ctx = new Proxy({}, {get: (_, key) => key === 'createLinearGradient' ? () => ({addColorStop() {}}) : () => {}, set: () => true});
  const canvas = {parentElement: {getBoundingClientRect: () => ({width: 500})}, style: {}, nextElementSibling: tip,
    setAttribute(key, value) {attrs[key] = value;}, getContext: () => ctx, getBoundingClientRect: () => ({left: 0})};
  app.context.document.getElementById = () => canvas;
  app.run('drawChart("balance-chart", [{date:"2026-11-01",balance_minor:12345,income_minor:12345,expense_minor:0},{date:"2026-11-02",balance_minor:12000,income_minor:0,expense_minor:345}])');
  assert.equal(canvas.height, 280);
  canvas.onfocus();
  canvas.onkeydown({key: 'Home', preventDefault() {}});
  assert.match(tip.textContent, /123\.45/);
  assert.match(attrs['aria-label'], /arrow keys/);
  canvas.onpointermove({clientX: 499});
  assert.match(tip.textContent, /120/);
  canvas.onpointerleave();
  assert.equal(tip.style.display, 'none');
});

test('chart period controls accept only supported ranges', () => {
  const app = setup();
  app.context.guarded = async () => {};
  app.events.get('click')({target: {closest: () => ({dataset: {chartDays: '90'}})}});
  assert.equal(app.run('dashboardEndpoint()'), '/dashboard?days=90');
  app.events.get('click')({target: {closest: () => ({dataset: {chartDays: '9999'}})}});
  assert.equal(app.run('dashboardEndpoint()'), '/dashboard?days=90');
});

test('business forecast renders exact daily records with stepped movement and rounded axes', async () => {
  const app = setup('#/seller/forecast?days=30');
  vm.runInContext(fs.readFileSync('app/static/v2-seller.js', 'utf8'), app.context);
  app.run(`S.route = ['seller', 'forecast']; api = async path => path.includes('/customers') ? [] : ({opening_minor:10000, days: [{date:'2026-11-22', balance_minor:10000,inflow_minor:0,outflow_minor:0}, {date:'2026-11-23', balance_minor:12345,inflow_minor:2345,outflow_minor:0}]});`);
  const html = await app.run('window.ContextIQSeller.pages.seller()');
  assert.match(html, /<polyline/);
  assert.match(html, /<title>[^<]*123\.45/);
  assert.match(html, /Day-by-day figures/);
  assert.doesNotMatch(html, /NaN|Infinity/);
});

test('Tara impact panel can collapse and retains its state on a data refresh', () => {
  const app = setup();
  app.context.data = {allocation:{committed_minor:10000,reserved_minor:0,savings_minor:1000},suggestions:[]};
  assert.match(app.run('aiImpact(data)'), /<details[^>]* open>/);
  app.events.get('toggle')({target:{open:false,matches:() => true}});
  assert.doesNotMatch(app.run('aiImpact(data)'), /<details[^>]* open>/);
  app.events.get('toggle')({target:{open:true,matches:() => true}});
  assert.match(app.run('aiImpact(data)'), /<details[^>]* open>/);
});
