"""Tiny production smoke test on a fresh fictional demo; never execute a payment."""
import json,time,sys
from pathlib import Path
import httpx
OUT=Path(__file__).resolve().parents[2]/'reports/evaluation-2026-11-23';OUT.mkdir(parents=True,exist_ok=True)
BASE='https://context-iq-v2-0.vercel.app'
with httpx.Client(base_url=BASE,timeout=60) as c:
 r=c.post('/api/v2/session',json={'persona':'freelancer'});r.raise_for_status();c.headers['x-csrf-token']=r.json()['csrf']
 ready=c.get('/api/v2/imports/templates')
 print('New backend ready',ready.status_code==200,flush=True)
 if ready.status_code!=200:sys.exit(2)
 p=c.get('/api/v2/profile').json();c.put('/api/v2/profile',json={**p,'name':'Meera','configuration':'business'}).raise_for_status()
 c.put('/api/v2/privacy',json={'allow_model_questions':True,'allow_model_records':True}).raise_for_status()
 before=c.get('/api/v2/dashboard').json()['finance']['balance_minor'];rows=[]
 for question in ['Show my recorded cash balance and explain the difference from available to spend.',
                  'What is outstanding on invoice INV-0004 for Bengaluru Fintech Labs?']:
  start=time.perf_counter();r=c.post('/api/v2/ask',json={'message':question});r.raise_for_status();d=r.json()
  rows.append({'question':question,'latency_ms':(time.perf_counter()-start)*1000,'routing':d.get('routing'),'answer':d.get('answer'),
               'retrieval':(d.get('analysis') or {}).get('retrieval'),'decision':(d.get('analysis') or {}).get('decision'),'sources':d.get('sources')})
  print('Observed',d.get('routing'),(d.get('analysis') or {}).get('retrieval',{}).get('status'),flush=True)
 after=c.get('/api/v2/dashboard').json()['finance']['balance_minor']
 c.put('/api/v2/privacy',json={'allow_model_questions':False,'allow_model_records':False}).raise_for_status()
 off=c.post('/api/v2/ask',json={'message':'Show my recorded balance'}).json()
 report={'source':BASE,'fictional_workspace':True,'rows':rows,'real_model_answer_count':sum(x['routing']=='retrieval_llm' for x in rows),
          'money_unchanged':before==after,'optout_stops_retrieval_reasoning':not (off.get('analysis') or {}).get('retrieval'),
          'limits':'Two smoke prompts only, not representative LLM accuracy, F1 or hallucination evaluation.'}
 (OUT/'live-groq.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
 print(json.dumps({k:v for k,v in report.items() if k!='rows'},indent=2),flush=True)
