"""Predeclared semantic bank; actual V2 /ask, private fictional local workspace."""
import os,sys,json,time,math,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));OUT=ROOT/'reports'/'evaluation-2026-11-22';OUT.mkdir(parents=True,exist_ok=True)
os.environ.update(DATABASE_URL='sqlite:///'+(OUT/('agent-'+uuid.uuid4().hex+'.db')).as_posix(),PAYPAL_ENV='mock',CONTEXTIQ_WORKER_MODE='off',CONTEXTIQ_LEGACY_TEST_AUTH='0',GROQ_API_KEY='',ANTHROPIC_API_KEY='')
os.environ['CONTEXTIQ_MOCK_STORE']=str(OUT/('agent-provider-'+uuid.uuid4().hex+'.json'))
from fastapi.testclient import TestClient
from app.main import app
from app.intelligence import llm
from app.v2_intelligence import route
from tools.evaluation.evaluate_models import scores,clean
import numpy as np
bank=json.loads((Path(__file__).parent/'agent_bank.json').read_text(encoding='utf-8'))
flat=[{'expected':label,'question':q,'language':'hi' if any('\u0900'<=x<='\u097f' for x in q) else 'kn' if any('\u0c80'<=x<='\u0cff' for x in q) else 'en'} for label,items in bank.items() for q in items]
assert len(flat)==96
llm.complete=lambda *a,**k: None
with TestClient(app) as c:
 csrf=c.post('/api/v2/session',json={'persona':'freelancer'}).json()['csrf'];c.headers['x-csrf-token']=csrf
 c.put('/api/v2/privacy',json={'allow_model_questions':False})
 before=c.get('/api/v2/dashboard').json();original=before['finance']['balance_minor'];rows=[]
 for case in flat:
  routed=route({'message':case['question'],'allow_model_questions':False})['topic']
  t=time.perf_counter();r=c.post('/api/v2/ask',json={'message':case['question']});elapsed=(time.perf_counter()-t)*1000
  if r.status_code!=200:rows.append({**case,'status':r.status_code,'latency_ms':elapsed});continue
  d=r.json();a=d.get('analysis') or {};metrics=a.get('metrics') or {}
  exact=metrics.get('opening_minor',0)+metrics.get('income_minor',0)-metrics.get('expense_minor',0)==metrics.get('balance_minor') if metrics else None
  allocation=metrics.get('balance_minor',0)-metrics.get('committed_minor',0)-metrics.get('reserved_minor',0)-metrics.get('savings_minor',0)==metrics.get('flexible_minor') if metrics else None
  rows.append({**case,'status':r.status_code,'actual':routed,'response_topic':d.get('topic'),'correct':case['expected']==routed,'routing':d.get('routing'),'latency_ms':elapsed,'answer_nonempty':bool(d.get('answer','').strip()),'has_analysis':bool(a),'has_calculations':bool(a.get('calculations')),'has_records':bool(a.get('records')),'numeric_ledger_identity':exact,'numeric_allocation_identity':allocation,'owned_links_only':all(x.get('destination','').startswith('#/') for x in a.get('records',[])),'answer':d.get('answer')})
 after=c.get('/api/v2/dashboard').json();available=[r for r in rows if r.get('status')==200]
 y=[r['expected'] for r in available];p=[r['actual'] for r in available]
 eligible=[r for r in available if r.get('has_analysis')];lat=[r['latency_ms'] for r in rows]
 result={'corpus':'96 newly predeclared developer-authored prompts; 16 balanced topics, 64 English, 16 Hindi, 16 Kannada. Not externally labeled or blind user data.','mode':'Actual local /api/v2/ask, LLM questions off, mock payments, isolated SQLite','metrics':scores(y,p),'languages':{language:scores([r['expected'] for r in available if r['language']==language],[r['actual'] for r in available if r['language']==language]) for language in ['en','hi','kn']},'api_success_count':len(available),'total':len(rows),'read_only_money':{'before_minor':original,'after_minor':after['finance']['balance_minor'],'passed':original==after['finance']['balance_minor']},'grounding':{'analysis_responses':len(eligible),'calculation_present':sum(r['has_calculations'] for r in eligible),'record_references_present':sum(r['has_records'] for r in eligible),'ledger_identity_pass':sum(r['numeric_ledger_identity'] is True for r in eligible),'allocation_identity_pass':sum(r['numeric_allocation_identity'] is True for r in eligible),'owned_link_format_pass':sum(r['owned_links_only'] for r in eligible),'limitation':'Identity checks validate returned structured metrics against their own equations, not the truth of every prose claim. Ownership format is not a permission test; isolation is tested separately.'},'latency':{'n':len(lat),'p50_ms':float(np.percentile(lat,50)),'p95_ms':float(np.percentile(lat,95)),'p99_ms':float(np.percentile(lat,99))},'rows':rows}
 result['corpus']='96 developer-authored prompts; 16 balanced topics; 66 English, 15 Hindi, 15 Kannada. This bank has been inspected during fixes and is now development regression data, not a blind test.'
 scenario=c.post('/api/v2/ask',json={'message': "Can I afford rent and the laptop EMI this week if Bengaluru Fintech Labs doesn't pay until January?"}).json()
 (OUT/'scenario-proof.json').write_text(json.dumps(scenario,indent=2,ensure_ascii=False),encoding='utf-8')
 (OUT/'agent.json').write_text(json.dumps(clean(result),indent=2,ensure_ascii=False),encoding='utf-8')
 print(json.dumps({k:v for k,v in result.items() if k not in ['rows','metrics','languages']},indent=2),flush=True)
