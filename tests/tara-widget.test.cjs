const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup() {
  const events = new Map(), storage = new Map(), attrs = new Set(['data-open']);
  const thread = {innerHTML:''}, field = {value:''}, send = {}, heading = {classList:{add(){}}};
  let mounted = false;
  const panel = {
    hidden:false, style:{removeProperty(name){delete this[name];}}, html:'',
    hasAttribute:name=>attrs.has(name),
    getBoundingClientRect(){return {left:parseFloat(this.style.left)||10,top:parseFloat(this.style.top)||10,width:parseFloat(this.style.width)||380,height:parseFloat(this.style.height)||420};},
    insertAdjacentHTML(_, html){this.html += html; mounted = true;},
    querySelector(selector){return ({'.tara-inline-thread':thread,'[data-tara-message]':field,'[data-tara-send]':send,'.guide-top > span':heading,'.tara-widget-chat':mounted ? {} : null})[selector]||null;},
    addEventListener(name, fn, capture){events.set(name+!!capture,fn);}, setPointerCapture(){},
  };
  const context = {S:{csrf:'fictional',route:['budget']}, document:{querySelector:()=>panel},
    window:{innerWidth:1000,innerHeight:800,addEventListener(){},setTimeout(){}},
    localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},
    messageHtml:row=>JSON.stringify(row), api:async()=>({answer:'Recorded answer',analysis:{records:['owned record']},destination:'#/budget'}),
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('app/static/v2-tara-widget.js','utf8'),context);
  const widget = context.window.ContextIQTaraWidget;
  widget.mount(panel,{open:true});
  return {context,widget,panel,thread,field,send,events,storage,attrs};
}

function dragTo(app, x, y) {
  const rect=app.panel.getBoundingClientRect();
  app.events.get('pointerdownfalse')({button:0,pointerId:2,clientX:rect.left+20,clientY:rect.top+20,target:{closest:s=>s.includes('.guide-top')?{}:null}});
  app.events.get('pointermovefalse')({pointerId:2,clientX:x+20,clientY:y+20,preventDefault(){}});
  app.events.get('pointerupfalse')({pointerId:2});
}

test('cursor dragging reaches all four corners without settings or dropdowns', () => {
  const app = setup();
  for (const [corner,x,y] of [['tl',12,12],['tr',668,12],['bl',12,368],['br',668,368]]) {
    dragTo(app,x,y);
    assert.equal(parseFloat(app.panel.style.left),x);
    assert.equal(parseFloat(app.panel.style.top),y);
  }
  assert.deepEqual(Object.keys(JSON.parse([...app.storage.values()][0])).sort(),['width','x','y']);
});

test('resizing and viewport changes keep the assistant inside the mobile safe area', () => {
  const app = setup();
  app.widget.setSize(10000,10000);
  assert.equal(parseFloat(app.panel.style.width),976);
  assert.equal(parseFloat(app.panel.style.height),776);
  app.context.window.innerWidth=390;app.context.window.innerHeight=740;
  app.widget.place();
  assert.equal(parseFloat(app.panel.style.width),366);
  assert(parseFloat(app.panel.style.top)+parseFloat(app.panel.style.height)<=652);
});

test('the minimized bubble can be dragged and stays on screen', () => {
  const app = setup(); app.attrs.delete('data-open'); app.widget.mount(app.panel,{open:false});
  app.events.get('pointerdownfalse')({button:0,pointerId:1,clientX:900,clientY:700,target:{closest:s=>s.includes('.guide-launch')?{}:null}});
  app.events.get('pointermovefalse')({pointerId:1,clientX:100,clientY:100,preventDefault(){}});
  app.events.get('pointerupfalse')({pointerId:1});
  assert(parseFloat(app.panel.style.left)>=12);
  assert(parseFloat(app.panel.style.top)>=12);
  assert.equal(parseFloat(app.panel.style.width),56);
});

test('inline questions reuse owned Ask Tara with evidence and never change the page', async () => {
  const app = setup(); let body;
  assert.match(app.panel.html,/class="tara-open-ask" href="#\/ask">Open Ask Tara/);
  app.context.api=async(path,data)=>{assert.equal(path,'/ask');body=data;return {answer:'Owned cash',analysis:{records:['owned evidence']}};};
  await app.widget.ask('How is my financial condition?');
  assert.equal(body.message,'How is my financial condition?');
  assert.match(app.thread.innerHTML,/owned evidence/);
  assert.equal(app.context.S.route[0],'budget');
  assert(![...app.storage.values()].join('').includes('financial'));
});

test('duplicate sends are blocked while waiting and the answer survives minimize/reopen', async () => {
  const app = setup(); let resolve, calls=0;
  app.context.api=()=>{calls++;return new Promise(done=>{resolve=done;});};
  const pending=app.widget.ask('My cash'); await app.widget.ask('Duplicate');
  assert.equal(calls,1); assert.equal(app.send.disabled,true);
  app.attrs.delete('data-open'); app.widget.mount(app.panel,{open:false});
  resolve({answer:'Saved reply'}); await pending;
  app.attrs.add('data-open'); app.widget.mount(app.panel,{open:true});
  assert.match(app.thread.innerHTML,/Saved reply/);
  assert.equal(app.send.disabled,false);
});

test('logout discards an in-flight answer and clears the private conversation', async () => {
  const app = setup(); let resolve;
  await app.widget.ask('Previous private question');
  app.context.api=()=>new Promise(done=>{resolve=done;});
  const pending=app.widget.ask('Private question');
  app.context.S.csrf='another-user';app.widget.resetSession();app.widget.mount(app.panel,{open:true});
  resolve({answer:'Old private answer'});await pending;
  assert.doesNotMatch(app.thread.innerHTML,/Previous private question|Recorded answer|Private question|Old private answer/);
});

test('offline failure leaves a readable answer and allows a retry', async () => {
  const app = setup(); app.context.api=async()=>{throw new Error('Offline');};
  await app.widget.ask('My cash');
  assert.match(app.thread.innerHTML,/Offline/);assert.equal(app.send.disabled,false);
  app.context.api=async()=>({answer:'Recovered'});await app.widget.ask('Try again');
  assert.match(app.thread.innerHTML,/Recovered/);
});

test('welcome help makes no authenticated or external model request', async () => {
  const app = setup();app.context.S.csrf='';
  app.context.api=()=>{throw new Error('Must not call an authenticated API');};
  await app.widget.ask('Where do I see my invoices?');
  assert.match(app.thread.innerHTML,/Back office/);
  assert.doesNotMatch(app.panel.html,/data-tara-dock|data-tara-reset|Choose corner|Reset layout/);
});

test('cursor position and keyboard resizing survive minimize and reopen', () => {
  const app = setup();dragTo(app,12,12);
  const before=parseFloat(app.panel.style.width);
  app.events.get('keydownfalse')({target:{matches:()=>true},key:'ArrowRight',preventDefault(){}});
  assert.equal(parseFloat(app.panel.style.width),before+20);
  app.attrs.delete('data-open');app.widget.mount(app.panel,{open:false});
  app.attrs.add('data-open');app.widget.mount(app.panel,{open:true});
  assert.equal(parseFloat(app.panel.style.left),12);
  assert.equal(parseFloat(app.panel.style.width),before+20);
});

test('draft and input selection can be restored across page guidance refreshes', () => {
  const app=setup();let selected;
  app.field.selectionStart=3;app.field.selectionEnd=5;app.field.focus=()=>{};
  app.field.setSelectionRange=(start,end)=>{selected=[start,end];};
  app.context.document.activeElement=app.field;
  app.field.value='Unsent draft';
  app.events.get('inputfalse')({target:{matches:()=>true,value:'Unsent draft'}});
  const saved=app.widget.captureFocus();app.widget.mount(app.panel,{open:true});app.widget.restoreFocus(saved);
  assert.equal(app.field.value,'Unsent draft');assert.deepEqual(selected,[3,5]);
});
