"""Actual browser -> API -> SQLite -> updated UI checks for the new flows."""
import os,sys,json,time,subprocess,uuid
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'reports/evaluation-2026-11-23';OUT.mkdir(exist_ok=True,parents=True);BASE='http://127.0.0.1:8051'
env=os.environ.copy();env.update(DATABASE_URL='sqlite:///'+(OUT/('browser-'+uuid.uuid4().hex+'.db')).as_posix(),PAYPAL_ENV='mock',CONTEXTIQ_WORKER_MODE='off',CONTEXTIQ_LEGACY_TEST_AUTH='0',GROQ_API_KEY='',ANTHROPIC_API_KEY='',PORT='8051')
subprocess.run(['node','build-contextiq.mjs'],cwd=ROOT,check=True);log=open(OUT/'browser-server.log','w',encoding='utf-8')
proc=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
try:
 for i in range(80):
  try:
   if httpx.get(BASE+'/health/live',timeout=1).status_code==200:break
  except httpx.HTTPError:pass
  time.sleep(.5)
 else:raise RuntimeError('Server did not start')
 c=httpx.Client(base_url=BASE,timeout=20);csrf=c.post('/api/v2/session',json={'persona':'freelancer'}).json()['csrf'];c.headers['x-csrf-token']=csrf
 profile=c.get('/api/v2/profile').json();c.put('/api/v2/profile',json={**profile,'name':'Meera','configuration':'business'})
 before=c.get('/api/v2/dashboard').json()['finance']['balance_minor'];checks={};errors=[];pages=[]
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True,args=['--disable-gpu']);ctx=browser.new_context(viewport={'width':1440,'height':900},accept_downloads=True)
  ctx.add_cookies([{'name':x.name,'value':x.value,'domain':x.domain,'path':x.path,'httpOnly':True,'sameSite':'Lax'} for x in c.cookies.jar]);ctx.add_init_script("localStorage.setItem('contextiq.tara-tour.v2','seen')")
  ctx.route('**/static/contextiq-*.js',lambda r:r.fulfill(path=str(ROOT/'contextiq-dist/static'/r.request.url.split('/')[-1]),content_type='application/javascript'));ctx.route(BASE+'/',lambda r:r.fulfill(path=str(ROOT/'contextiq-dist/index.html'),content_type='text/html'))
  page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
  def go(route):page.goto(BASE+'/#/'+route,wait_until='networkidle');page.wait_for_timeout(300)
  go('seller/forecast');page.get_by_text('Build a read-only cash scenario',exact=True).click();page.get_by_label('Days to cover',exact=True).fill('14');page.get_by_label('Hypothetical opening cash (₹, optional)',exact=True).fill('1000');page.get_by_role('button',name='Preview decision',exact=True).click();page.wait_for_timeout(700)
  checks['scenario_preview_rendered']=page.locator('#scenario-preview-result .decision-card').count()==1
  checks['scenario_did_not_change_cash']=c.get('/api/v2/dashboard').json()['finance']['balance_minor']==before
  page.screenshot(path=str(OUT/'scenario-editor.png'))
  go('seller/import');page.locator('#csv-kind').select_option('transactions');page.locator('#csv-text').fill('title,amount,direction,date,purpose,category,external_id\nUI receipt,100.50,income,2026-11-23,business,sales,ui-receipt-001');page.get_by_role('button',name='Preview import',exact=True).click();page.wait_for_timeout(500)
  checks['preview_without_cash_change']=c.get('/api/v2/dashboard').json()['finance']['balance_minor']==before
  page.locator('#csv-confirm-form input[name="confirmed"]').check();page.get_by_role('button',name='Confirm import',exact=True).click();page.wait_for_timeout(600)
  checks['confirmed_import_updates_cash']=c.get('/api/v2/dashboard').json()['finance']['balance_minor']==before+10050
  with page.expect_download() as downloaded:page.locator('#download-workspace').click()
  data=json.loads(Path(downloaded.value.path()).read_text(encoding='utf-8'));checks['export_contains_confirmed_ledger']=any(r['title']=='UI receipt' for r in data['ledger'])
  go('purchases/before');page.get_by_text('See how a price drop changes a savings plan',exact=True).click();page.get_by_role('button',name='Run price-drop demo',exact=True).click();page.wait_for_timeout(800)
  checks['price_drop_visible']=page.locator('.price-impact').count()==1 and '17.5%' in page.locator('.price-impact').inner_text()
  watches=c.get('/api/v2/watch').json();watch=next(w for w in watches if w['price_effect']['simulated'])
  checks['price_drop_updates_savings_target']=watch['price_effect']['target_minor']==990000 and watch['price_effect']['plan_updated']
  checks['price_drop_keeps_recorded_cash']=c.get('/api/v2/dashboard').json()['finance']['balance_minor']==before+10050
  page.screenshot(path=str(OUT/'price-drop-desktop.png'),full_page=True)
  page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(OUT/'price-drop-mobile.png'),full_page=True);page.set_viewport_size({'width':1440,'height':900})
  go('transparency');page.locator('#privacy-form input[name="allow_model_questions"]').check();page.locator('#privacy-form input[name="allow_model_records"]').check();page.get_by_role('button',name='Save AI choice').click();page.wait_for_timeout(500)
  checks['record_consent_persisted']=c.get('/api/v2/transparency').json()['model_records_enabled'] is True
  go('ask');page.get_by_placeholder('Ask a question',exact=True).fill('Show my recorded cash balance');page.locator('#ask-form button[type="submit"]').click();page.wait_for_timeout(1500)
  checks['retrieval_visible']=page.locator('.retrieval-badge').count()>0
  checks['sources_inspectable']=page.locator('.retrieval-proof a').count()>0
  page.screenshot(path=str(OUT/'tara-retrieval.png'),full_page=True)
  axe=ROOT/'reports/evaluation-2026-11-22/axe.min.js'
  for width,height in [(1440,900),(390,844)]:
   page.set_viewport_size({'width':width,'height':height})
   for route in ['home','ask','seller/forecast','seller/import','transparency','watch/'+watch['id']]:
    go(route);page.add_script_tag(content=axe.read_text(encoding='utf-8'))
    a=page.evaluate("""async()=>{const a=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return {violations:a.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target)})),incomplete:a.incomplete.length,overflow:document.documentElement.scrollWidth>innerWidth+1}}""")
    pages.append({'width':width,'route':route,**a});print('BROWSER',width,route,len(a['violations']),a['overflow'],flush=True)
  browser.close()
 result={'checks':checks,'javascript_errors':errors,'pages':pages,'scope':'Local shipped bundle, actual API and isolated SQLite. Model unavailable locally; separately verify Groq in production.'};(OUT/'browser-checks.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(checks,flush=True)
 assert all(checks.values()) and not errors,result
finally:proc.terminate();proc.wait(timeout=15);log.close()
