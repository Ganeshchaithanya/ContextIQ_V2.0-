import os,sys,json,time,subprocess
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'reports'/'evaluation-2026-11-22';BASE='http://127.0.0.1:8033'
env=os.environ.copy();env.update(DATABASE_URL='sqlite:///'+(OUT/'browser-fixes.db').as_posix(),PAYPAL_ENV='mock',CONTEXTIQ_WORKER_MODE='off',CONTEXTIQ_LEGACY_TEST_AUTH='0',GROQ_API_KEY='',ANTHROPIC_API_KEY='',PORT='8033')
subprocess.run(['node','build-contextiq.mjs'],cwd=ROOT,check=True)
log=open(OUT/'browser-server.log','w',encoding='utf-8')
server=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
try:
 for i in range(60):
  try:
   if httpx.get(BASE+'/health/live',timeout=1).status_code==200:break
  except httpx.HTTPError:pass
  time.sleep(.5)
 else:raise RuntimeError('Local server failed to start')
 http=httpx.Client(base_url=BASE,timeout=20);csrf=http.post('/api/v2/session',json={'persona':'freelancer'}).json()['csrf'];http.headers['x-csrf-token']=csrf
 prof=http.get('/api/v2/profile').json();http.put('/api/v2/profile',json={**prof,'name':'Meera','configuration':'business','allow_model_questions':False}).raise_for_status()
 checks={};issues=[]
 with sync_playwright() as p:
  b=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True,args=['--disable-gpu']);c=b.new_context(viewport={'width':1440,'height':900})
  c.add_cookies([{'name':x.name,'value':x.value,'domain':x.domain,'path':x.path,'httpOnly':True,'sameSite':'Lax'} for x in http.cookies.jar])
  c.add_init_script("localStorage.setItem('contextiq.tara-tour.v2','seen')")
  # Exercise the shipped ordered bundle against the real local API.
  c.route('**/static/contextiq-*.js',lambda r:r.fulfill(path=str(ROOT/'contextiq-dist'/'static'/r.request.url.split('/')[-1]),content_type='application/javascript'))
  c.route(BASE+'/',lambda r:r.fulfill(path=str(ROOT/'contextiq-dist/index.html'),content_type='text/html'))
  pg=c.new_page();errors=[];pg.on('pageerror',lambda e:errors.append(str(e)))
  pg.goto(BASE+'/#/ask',wait_until='networkidle');pg.get_by_placeholder('Ask a question',exact=True).fill("Can I afford rent and the laptop EMI this week if Bengaluru Fintech Labs doesn't pay until January?")
  pg.get_by_role('button',name='Send',exact=False).first.click();pg.wait_for_timeout(900)
  checks['scenario_answer_in_ui']=pg.get_by_text('Yes.',exact=False).count()>0
  pg.screenshot(path=str(OUT/'fixed-scenario.png'),full_page=True)
  checks['bundle_executed_without_js_errors']=not errors
  for width,height in [(1440,900),(390,844)]:
   for route in ['home','seller','budget/allocation','ask','knowledge','transparency']:
    pg.set_viewport_size({'width':width,'height':height});pg.goto(BASE+'/#/'+route,wait_until='networkidle');pg.wait_for_timeout(250)
    pg.add_script_tag(content=(OUT/'axe.min.js').read_text(encoding='utf-8'))
    a=pg.evaluate("""async()=>{const a=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return {violations:a.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target)})),incomplete:a.incomplete.length,overflow:document.documentElement.scrollWidth>innerWidth+1}}""")
    if a['overflow']:
     a['overflow_elements']=pg.evaluate("""()=>[...document.querySelectorAll('main *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1 && getComputedStyle(e).position!=='fixed').slice(0,12).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width}))""")
    issues.append({'width':width,'route':route,**a});print(width,route,'issues',len(a['violations']),'overflow',a['overflow'],flush=True)
  b.close()
 checks['no_page_overflow']=not any(x['overflow'] for x in issues)
 checks['critical_scenario_test']=checks['scenario_answer_in_ui']
 data={'checks':checks,'javascript_errors':errors,'pages':issues,'scope':'Local updated code, shipped bundle; existing live-site measurements remain pre-fix. Not an accessibility certification.'}
 (OUT/'fix-verification.json').write_text(json.dumps(data,indent=2),encoding='utf-8');print(checks,flush=True)
finally:
 server.terminate();server.wait(timeout=15);log.close()
