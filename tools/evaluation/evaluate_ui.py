"""Low-volume deployed-site lab checks, including axe; no real payment actions."""
import io,json,sys,time,tarfile
from pathlib import Path
import httpx,numpy as np
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'reports'/'evaluation-2026-11-22';OUT.mkdir(parents=True,exist_ok=True)
BASE='https://context-iq-v2-0.vercel.app';VERSION='4.14.1'
axe=OUT/'axe.min.js'
if not axe.exists():
 data=httpx.get(f'https://registry.npmjs.org/axe-core/-/axe-core-{VERSION}.tgz',timeout=60).content
 with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as tf:axe.write_bytes(tf.extractfile('package/axe.min.js').read())
http=httpx.Client(base_url=BASE,timeout=90);session=http.post('/api/v2/session',json={'persona':'freelancer'});session.raise_for_status();csrf=session.json()['csrf'];http.headers['x-csrf-token']=csrf
profile=http.get('/api/v2/profile').json();http.put('/api/v2/profile',json={**profile,'name':'Meera','configuration':'business','allow_model_questions':False}).raise_for_status()
result={'source':BASE,'axe_version':VERSION,'mode':'Headless desktop Chrome, no network or CPU throttling. Lab samples, not CrUX field Core Web Vitals.','pages':[],'widget':{},'api':[]}
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True,args=['--disable-gpu'])
 ctx=browser.new_context(viewport={'width':1440,'height':900})
 ctx.add_cookies([{'name':x.name,'value':x.value,'domain':x.domain,'path':x.path,'secure':x.secure,'httpOnly':True,'sameSite':'Lax'} for x in http.cookies.jar])
 ctx.add_init_script("""localStorage.setItem('contextiq.tara-tour.v2','seen');window.__lab={lcp:0,cls:0,events:[]};try{new PerformanceObserver(l=>{for(const e of l.getEntries())window.__lab.lcp=e.startTime}).observe({type:'largest-contentful-paint',buffered:true});new PerformanceObserver(l=>{for(const e of l.getEntries())if(!e.hadRecentInput)window.__lab.cls+=e.value}).observe({type:'layout-shift',buffered:true});new PerformanceObserver(l=>{for(const e of l.getEntries())if(e.interactionId)window.__lab.events.push(e.duration)}).observe({type:'event',buffered:true,durationThreshold:16})}catch(e){}""")
 for width,height in [(1440,900),(390,844)]:
  for route in ['home','seller','budget/allocation','ask','knowledge','transparency']:
   page=ctx.new_page();page.set_viewport_size({'width':width,'height':height});errors=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   start=time.perf_counter();response=page.goto(BASE+'/#/'+route,wait_until='networkidle',timeout=90000);page.wait_for_timeout(600)
   await_ms=(time.perf_counter()-start)*1000
   page.add_script_tag(content=axe.read_text(encoding='utf-8'))
   audit=page.evaluate("""async()=>{const a=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return {violations:a.violations.map(v=>({id:v.id,impact:v.impact,help:v.help,helpUrl:v.helpUrl,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})),passes:a.passes.length,incomplete:a.incomplete.length}}""")
   perf=page.evaluate("""()=>({navigation:performance.getEntriesByType('navigation')[0].toJSON(),paint:performance.getEntriesByType('paint').map(x=>({name:x.name,time:x.startTime})),lcp_ms:window.__lab.lcp,cls:window.__lab.cls,event_durations_ms:window.__lab.events,viewport:innerWidth,document_width:document.documentElement.scrollWidth,heading:document.querySelector('main h1')?.textContent})""")
   row={'route':route,'width':width,'height':height,'http_status':response.status,'ready_wait_ms':await_ms,'performance':perf,'horizontal_overflow':perf['document_width']>width+1,'javascript_errors':errors,'axe':audit}
   result['pages'].append(row)
   if route=='home':page.screenshot(path=str(OUT/f'ui-home-{width}.png'))
   if width==1440 and route=='home':
    if page.locator('[data-guide="open"]').count():page.locator('[data-guide="open"]').click()
    field=page.locator('#tara-inline-question');field.fill('Show my recorded balance')
    panel=page.locator('#visual-guide');before=panel.bounding_box()
    page.locator('[data-guide="minimize"]').click();page.locator('[data-guide="open"]').click()
    result['widget']['draft_restored']=field.input_value()=='Show my recorded balance'
    handle=page.locator('.guide-top');box=handle.bounding_box();page.mouse.move(box['x']+60,box['y']+15);page.mouse.down();page.mouse.move(box['x']-120,box['y']-140,steps=10);page.mouse.up()
    after=panel.bounding_box();result['widget']['drag_changed_position']=abs(after['x']-before['x'])>20 or abs(after['y']-before['y'])>20
    result['widget']['inside_viewport']=after['x']>=0 and after['y']>=0 and after['x']+after['width']<=width+1 and after['y']+after['height']<=height+1
    page.get_by_role('link',name='Budget',exact=True).first.click();page.wait_for_timeout(900)
    result['widget']['draft_preserved_across_page']=field.input_value()=='Show my recorded balance'
   page.close();(OUT/'ui.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print('UI',width,route,'axe issues',len(audit['violations']),flush=True)
 ctx.close();browser.close()
for _ in range(8):
 t=time.perf_counter();r=http.get('/api/v2/dashboard');result['api'].append({'endpoint':'dashboard','status':r.status_code,'latency_ms':(time.perf_counter()-t)*1000})
result['api_latency']={k:float(np.percentile([x['latency_ms'] for x in result['api']],v)) for k,v in [('p50_ms',50),('p95_ms',95),('p99_ms',99)]}
# A tiny, predeclared probe can establish whether the remote classifier actually ran;
# it cannot establish general LLM correctness or a stable aggregate score.
http.put('/api/v2/privacy',json={'allow_model_questions':True})
prompts=[('balance','How large is the cash cushion currently sitting in my till?'),('goal','Am I close to funding the replacement freezer?'),('focus','Which action deserves my attention first?'),('payment','Did the bank debit actually settle?'),('overview','Give me a complete picture of the condition of my shop'),('emi','What monthly repayments are still outstanding?')]
live=[]
for expected,q in prompts:
 t=time.perf_counter();r=http.post('/api/v2/ask',json={'message':q});d=r.json();live.append({'question':q,'expected':expected,'status':r.status_code,'topic':d.get('topic'),'routing':d.get('routing'),'correct':d.get('topic')==expected,'latency_ms':(time.perf_counter()-t)*1000})
result['live_model_probe']={'rows':live,'llm_routed_n':sum(x.get('routing')=='llm' for x in live),'total':len(live),'note':'Six probes only. An absence of llm routing is not proof that no credentials exist: timeout, rate limit, parsing failure and backend availability can also trigger fallback.'}
http.put('/api/v2/privacy',json={'allow_model_questions':False})
r=http.get('/');headers={k.lower():v for k,v in r.headers.items()};cookie=session.headers.get('set-cookie','').lower()
result['headers']={k:headers.get(k) for k in ['content-security-policy','strict-transport-security','x-content-type-options','referrer-policy','permissions-policy','x-frame-options']}
result['session_cookie_attributes']={'httponly':'httponly' in cookie,'secure':'secure' in cookie,'samesite_lax':'samesite=lax' in cookie,'value_saved':False}
(OUT/'ui.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print('DEPLOYED UI EVALUATION COMPLETE',flush=True)
