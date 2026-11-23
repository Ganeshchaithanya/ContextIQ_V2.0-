"""Locked primary-source retrieval benchmark and independent arithmetic oracle.

No bank-driven tuning in this run. Not a human-labeled real-world accuracy claim.
"""
import os,json,sys,hashlib,uuid,tempfile,random,time
from pathlib import Path
from datetime import timedelta
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));OUT=ROOT/'reports/evaluation-2026-11-23';OUT.mkdir(parents=True,exist_ok=True)
os.environ.update(PAYPAL_ENV='mock',CONTEXTIQ_WORKER_MODE='off',CONTEXTIQ_LEGACY_TEST_AUTH='0',GROQ_API_KEY='',ANTHROPIC_API_KEY='')
db=OUT/('benchmark-'+uuid.uuid4().hex+'.db');os.environ['DATABASE_URL']='sqlite:///'+db.as_posix();os.environ['CONTEXTIQ_MOCK_STORE']=str(OUT/'benchmark-provider.json')
from fastapi.testclient import TestClient
from app.main import app
from app.v2_seller import today
from tools.backup_restore import backup,restore
bankpath=Path(__file__).parent/'retrieval_bank.json';bank=json.loads(bankpath.read_text(encoding='utf-8'));digest=hashlib.sha256(bankpath.read_bytes()).hexdigest()
with TestClient(app) as c:
 def session(persona):
  c.cookies.clear();c.headers['x-csrf-token']=c.post('/api/v2/session',json={'persona':persona}).json()['csrf']
 session('freelancer')
 invs=c.get('/api/v2/seller/invoices').json();customers=c.get('/api/v2/seller/customers').json();bills=c.get('/api/v2/seller/bills').json()
 results=[]
 for case in bank:
  source=case['primary_source']
  if source.startswith('invoice_number:'):source='invoice:'+next(x['id'] for x in invs if x['number']==source.split(':',1)[1])
  if source.startswith('customer_name:'):source='customer:'+next(x['id'] for x in customers if x['name']==source.split(':',1)[1])
  if source.startswith('bill_name:'):source='bill:studio:'+next(x['id'] for x in bills if x['name']==source.split(':',1)[1])
  t=time.perf_counter();r=c.post('/api/v2/retrieval/search',json={'message':case['question']});r.raise_for_status();docs=r.json()['sources'];ids=[d['source_id'] for d in docs]
  rank=ids.index(source)+1 if source in ids else None
  results.append({**case,'resolved_source':source,'rank':rank,'hits':{str(k):rank is not None and rank<=k for k in [1,3,5,8]},'latency_ms':(time.perf_counter()-t)*1000,'returned_sources':ids})
 # Controlled records, all invoice due dates are relative and no recurrence: oracle
 # does not import or reuse the application's scenario/bill-offset functions.
 session('salaried');c.put('/api/v2/seller/settings',json={'upi_vpa':'demo@bank','payee_name':'Oracle business','opening_balance_minor':100000})
 client=c.post('/api/v2/seller/customers',json={'name':'Oracle Client','usual_payment_delay_days':0}).json();clientid=client['id'];base=today()
 receipts=[(2,70000),(8,130000),(18,50000)]
 for day,amount in receipts:
  inv=c.post('/api/v2/seller/invoices',json={'customer_id':clientid,'issue_date':base.isoformat(),'due_date':(base+timedelta(days=day)).isoformat(),'lines':[{'description':'Controlled work','quantity':1,'unit_price_minor':amount}]}).json()
  c.post('/api/v2/seller/invoices/'+inv['id']+'/send').raise_for_status()
 bills=[(1,30000),(6,90000),(16,50000)]
 for day,amount in bills:c.post('/api/v2/seller/bills',json={'name':'Controlled bill '+str(day),'amount_minor':amount,'due_date':(base+timedelta(days=day)).isoformat(),'recurrence':'none'}).raise_for_status()
 rng=random.Random(891723);oracle=[]
 for i in range(30):
  horizon=rng.choice([7,14,30]);delay=rng.choice([0,5,20]);extra=rng.choice([0,10000,80000]);opening=rng.choice([20000,100000,300000]);exclude=rng.choice([False,True]);value=opening;expected=[]
  for day in range(horizon):
   incoming=sum(amt for due,amt in receipts if due+delay==day) if not exclude else 0
   outgoing=sum(amt for due,amt in bills if due==day)+(extra if day==0 else 0)
   value+=incoming-outgoing;expected.append(value)
  d=c.post('/api/v2/seller/scenario',json={'horizon_days':horizon,'customer_id':clientid,'delay_days':delay,'exclude_client_receipts':exclude,'extra_expense_minor':extra,'cash_override_minor':opening}).json()['analysis']['scenario']
  oracle.append({'case':i,'passed':[x['balance_minor'] for x in d['days']]==expected,'expected_ending':expected[-1],'actual_ending':d['ending_minor']})
 before=c.get('/api/v2/dashboard').json()['finance']['balance_minor']
 # Restore only to a new file, never touch the running source database.
 backup_file=OUT/('sqlite-backup-'+uuid.uuid4().hex+'.db');restored=OUT/('sqlite-restored-'+uuid.uuid4().hex+'.db')
 backup('sqlite:///'+db.as_posix(),backup_file);restore(backup_file,'sqlite:///'+restored.as_posix())
 import sqlite3
 with sqlite3.connect(db) as a,sqlite3.connect(restored) as b:
  tables=[x[0] for x in a.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
  counts={t:(a.execute('select count(*) from "'+t+'"').fetchone()[0],b.execute('select count(*) from "'+t+'"').fetchone()[0]) for t in tables}
  restored_ok=all(x==y for x,y in counts.values()) and b.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 report={'corpus_sha256':digest,'retrieval_n':len(results),'primary_source_hit_at':{str(k):sum(r['hits'][str(k)] for r in results)/len(results) for k in [1,3,5,8]},'mrr_at_8':sum(1/r['rank'] if r['rank'] else 0 for r in results)/len(results),
 'retrieval_cases':results,'oracle_cases':oracle,'oracle_passed':sum(x['passed'] for x in oracle),'oracle_n':len(oracle),'sqlite_restore_integrity':restored_ok,'tables_checked':len(counts),
 'limits':'Developer-authored, newly frozen primary-source bank. Not independent human labeling; hit rate is not complete retrieval precision/recall. Arithmetic oracle uses independently written loops over controlled records. This does not establish live Groq answer accuracy or durable hosted storage.'}
 (OUT/'retrieval-evaluation.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k not in ['retrieval_cases','oracle_cases']},indent=2),flush=True)
