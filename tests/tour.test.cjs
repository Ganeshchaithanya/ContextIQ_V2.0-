const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

function setup(saved = {}, viewport = [1280, 900]) {
  const storage = new Map(Object.entries(saved)), nodes = new Map(), events = new Map(), timers = new Map();
  let now = 0, nextTimer = 1;
  function element(rect = {left: 20, top: 110, right: 350, bottom: 210, width: 330, height: 100}) {
    const classes = new Set(), attributes = new Map(), children = new Map();
    return {
      hidden: false, open: false, innerHTML: "", textContent: "", attributes, classes, scrolled: 0,
      style: {removeProperty(name) { delete this[name]; }},
      classList: {add: name => classes.add(name), remove: name => classes.delete(name)},
      addEventListener(name, fn) { this[name] = fn; },
      setAttribute(name, value) { attributes.set(name, value); },
      removeAttribute(name) { attributes.delete(name); },
      toggleAttribute(name, enabled) { if (enabled) attributes.set(name, ""); else attributes.delete(name); },
      closest() { return null; },
      getBoundingClientRect() { return rect; },
      scrollIntoView() { this.scrolled++; }, focus() {},
      querySelector(selector) { if (!children.has(selector)) children.set(selector, element()); return children.get(selector); },
    };
  }
  const query = selector => {
    if (selector === "#main .error-page" || selector === "[data-tara-next-tip]") return null;
    if (!nodes.has(selector)) nodes.set(selector, element());
    return nodes.get(selector);
  };
  nodes.set("#visual-guide", element({left: 0, top: 0, right: 360, bottom: 290, width: 360, height: 290}));
  const context = {
    S: {csrf: "fictional", profile: {onboarded: true}, route: ["home"], dashboard: null},
    $: query, t: text => text, esc: text => String(text), console, Map, Set, Date,
    localStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)},
    document: {hidden: false, addEventListener(name, fn) { events.set(name, fn); }},
    window: {innerWidth: viewport[0], innerHeight: viewport[1], setInterval() {},
      setTimeout(fn, delay) { const id = nextTimer++; timers.set(id, {fn, due: now + delay}); return id; },
      clearTimeout(id) { timers.delete(id); },
      addEventListener(name, fn) { events.set(name, fn); },
      requestAnimationFrame(fn) { context.frame = fn; return 1; }},
    navigate(route) { context.S.route = route.split("/"); vm.runInContext("guide.clear(); guide.update()", context); },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../app/static/v2-guide.js"), "utf8"), context);
  const update = () => vm.runInContext("guide.update()", context);
  const click = command => query("#visual-guide").click({target: {closest: () => ({dataset: {guide: command}})}});
  const tick = milliseconds => {
    const end = now + milliseconds;
    while (true) {
      const next = [...timers].filter(([, timer]) => timer.due <= end).sort((a, b) => a[1].due - b[1].due)[0];
      if (!next) break;
      const [id, timer] = next; timers.delete(id); now = timer.due; timer.fn();
    }
    now = end;
  };
  return {context, nodes, storage, events, query, update, click, tick, timers};
}

test("automatic tour spotlights and scrolls the first step without changing the page markup", () => {
  const app = setup({"contextiq.tara-tour.v1": "seen"});
  const target = app.query(".balance-card");
  target.innerHTML = "Original balance card";
  app.update();
  assert.equal(target.scrolled, 1);
  assert.equal(target.innerHTML, "Original balance card");
  assert(target.classes.has("guide-tour-target"));
  assert.equal(app.query("#tour-spotlight").hidden, false);
  assert(app.query("#visual-guide").attributes.has("data-tour"));
  assert.match(app.query("#visual-guide").querySelector(".guide-controls").innerHTML, /Step 1 of 7/);
  app.update();
  assert.equal(target.scrolled, 1, "background refresh must not repeatedly scroll the user");
});

test("seven steps navigate automatically, and finish restores normal page presentation", () => {
  const app = setup();
  app.update();
  for (const route of ["seller", "seller/invoices", "seller/forecast", "budget/allocation", "purchases", "knowledge"]) {
    app.click("tour-next");
    assert.equal(app.context.S.route.join("/"), route);
    assert.equal(app.query("#tour-spotlight").hidden, false);
  }
  app.click("tour-next");
  assert.equal(app.query("#tour-spotlight").hidden, true);
  assert(!app.query("#visual-guide").attributes.has("data-tour"));
  assert.equal(app.query("#visual-guide").style.top, undefined);
  assert.equal(app.storage.get("contextiq.tara-tour.v2"), "seen");
});

test("Escape and Skip stop the current tour; returning users can replay it manually", () => {
  const app = setup();
  app.update();
  let prevented = false;
  app.events.get("keydown")({key: "Escape", preventDefault() { prevented = true; }});
  assert(prevented);
  assert.equal(app.query("#tour-spotlight").hidden, true);
  assert(!app.query(".balance-card").classes.has("guide-tour-target"));
  app.update();
  assert(!app.query("#visual-guide").attributes.has("data-tour"));
  vm.runInContext("guide.startTour()", app.context);
  assert.equal(app.query("#tour-spotlight").hidden, false);
  app.click("tour-skip");
  assert.equal(app.query("#tour-spotlight").hidden, true);
  const returning = setup({"contextiq.tara-tour.v2": "seen"});
  returning.update();
  assert(!returning.query("#visual-guide").attributes.has("data-tour"));
});

test("mobile panel stays inside the viewport and scroll updates follow the target", () => {
  const app = setup({}, [390, 740]);
  app.update();
  const panel = app.query("#visual-guide"), spot = app.query("#tour-spotlight");
  assert(parseFloat(panel.style.left) >= 12);
  assert(parseFloat(panel.style.left) + parseFloat(panel.style.width) <= 378);
  assert(parseFloat(panel.style.top) + 290 <= 728);
  app.query(".balance-card").getBoundingClientRect = () => ({left: 20, right: 350, top: -300, bottom: -200, width: 330, height: 100});
  app.events.get("scroll")();
  app.context.frame();
  assert.equal(spot.hidden, true, "offscreen target must not leave a misleading spotlight");
});

test("opening a dialog hides the spotlight and restores it after closing", () => {
  const app = setup();
  app.update();
  app.query("#dialog").open = true;
  app.update();
  assert.equal(app.query("#tour-spotlight").hidden, true);
  app.query("#dialog").open = false;
  app.update();
  assert.equal(app.query("#tour-spotlight").hidden, false);
});

test("Tara remains available after the tour and on the anonymous payment entry screen", () => {
  const app = setup({"contextiq.tara-tour.v2": "seen"});
  app.context.S.route = ["transparency"];
  app.update();
  assert.equal(app.query("#visual-guide").hidden, false);
  app.context.S.csrf = "";
  app.context.S.route = ["scan"];
  app.update();
  assert.equal(app.query("#visual-guide").hidden, false);
  app.click("open");
  assert.match(app.query("#visual-guide").innerHTML, /Your payment starts here/);
  assert.match(app.query("#visual-guide").innerHTML, /never approves a payment/);
});


test("tour steps advance only when the user selects Next", () => {
  const app = setup(); app.update(); app.tick(60000); app.update();
  assert.equal(app.context.S.route.join("/"), "home");
  assert.equal(app.timers.size, 0);
  app.click("tour-next");
  assert.equal(app.context.S.route.join("/"), "seller");
});

test("minimizing preserves the same step and reopens the full guide", () => {
  const app = setup(); app.update(); app.click("tour-next");
  const panel = app.query("#visual-guide");
  app.click("minimize");
  assert.equal(panel.hidden, false);
  assert(panel.attributes.has("data-minimized"));
  assert.match(panel.innerHTML, /Open Tara visual guide/);
  assert.equal(app.query("#tour-spotlight").hidden, true);
  app.tick(60000);
  assert.equal(app.context.S.route.join("/"), "seller");
  app.click("open");
  assert.match(panel.innerHTML, /See who owes you/);
  assert.equal(app.query("#tour-spotlight").hidden, false);
  app.click("tour-next");
  assert.equal(app.context.S.route.join("/"), "seller/invoices");
});

test("background tabs and modal dialogs never advance the tour", () => {
  const app = setup(); app.update();
  app.context.document.hidden = true; app.events.get("visibilitychange")(); app.tick(9000);
  assert.equal(app.context.S.route[0], "home");
  app.context.document.hidden = false; app.events.get("visibilitychange")();
  app.query("#dialog").open = true; app.update(); app.tick(9000);
  assert.equal(app.context.S.route[0], "home");
  app.query("#dialog").open = false; app.update(); app.tick(9000);
  assert.equal(app.context.S.route[0], "home");
});

test("returning logins do not restart the tour; manual replay still works", () => {
  const app = setup(); app.update(); app.click("tour-skip"); app.update();
  app.context.S.csrf = "another-fictional-session";
  app.update();
  assert(!app.query("#visual-guide").attributes.has("data-tour"));
  vm.runInContext("guide.startTour()", app.context);
  assert(app.query("#visual-guide").attributes.has("data-tour"));
});

test("the manual tour finishes at Home for recommendations", () => {
  const app = setup(); app.update();
  for (let i = 0; i < 7; i++) app.click("tour-next");
  assert.equal(app.context.S.route.join("/"), "home");
  assert(!app.query("#visual-guide").attributes.has("data-tour"));
  assert.equal(app.timers.size, 0);
});

test("logging out clears private guidance and cancels the pending tour", () => {
  const app = setup(); app.update();
  app.context.S.csrf = "";
  vm.runInContext("guide.clear()", app.context);
  assert.equal(app.query("#visual-guide").hidden, true);
  assert.equal(app.timers.size, 0);
  app.context.S.csrf = "new-login";
  app.update();
  assert(!app.query("#visual-guide").attributes.has("data-tour"));
});

test("Tara remains available when an invoice has no actionable payment", () => {
  const app = setup();
  app.context.S.route = ["invoice", "cancelled-demo"];
  app.context.S.invoice = {id:"cancelled-demo",status:"cancelled"};
  app.update();
  assert.equal(app.query("#visual-guide").hidden, false);
  assert.match(app.query("#visual-guide").innerHTML, /Open Tara visual guide/);
});

test("Tara is available across every app section, welcome and onboarding", () => {
  const app=setup({"contextiq.tara-tour.v2":"seen"});
  for (const page of ['home','seller','budget','purchases','activity','ask','knowledge','transparency','preferences','scan','invoice','watch','notifications']) {
    app.context.S.route=[page];app.update();
    assert.equal(app.query('#visual-guide').hidden,false,page);
  }
  app.context.S.route=['home'];app.context.S.csrf='';app.update();
  assert.equal(app.query('#visual-guide').hidden,false,'welcome');
  app.context.S.csrf='new';app.context.S.profile.onboarded=false;app.update();
  assert.equal(app.query('#visual-guide').hidden,false,'onboarding');
});

test("an opened Tara stays expanded when navigating to another page", () => {
  const app=setup({"contextiq.tara-tour.v2":"seen"});
  app.update();app.click('open');
  for (const page of ['budget','seller','ask','preferences']) {
    app.context.S.route=[page];app.update();
    assert(app.query('#visual-guide').attributes.has('data-open'),page);
  }
});

test("Tara stays inside a modal's accessible layer and returns to the page afterward", () => {
  const app=setup({"contextiq.tara-tour.v2":"seen"});
  const body={append(node){node.parentElement=this;}};
  const dialog=app.query('#dialog');dialog.append=function(node){node.parentElement=this;};
  app.context.document.body=body;
  app.update();app.click('open');
  dialog.open=true;app.update();
  const panel=app.query('#visual-guide');
  assert.equal(panel.hidden,false);assert.equal(panel.parentElement,dialog);
  assert.match(panel.innerHTML,/Tara is here to help/);
  dialog.open=false;app.update();
  assert.equal(panel.parentElement,body);assert(panel.attributes.has('data-open'));
});
