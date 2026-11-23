"""Scoped retrieval, model guardrails, scenario arithmetic and preview-confirm imports."""
import os,tempfile,uuid,json
from pathlib import Path
os.environ.update(PAYPAL_ENV='mock',CONTEXTIQ_WORKER_MODE='off',CONTEXTIQ_LEGACY_TEST_AUTH='0',GROQ_API_KEY='',ANTHROPIC_API_KEY='')
os.environ['DATABASE_URL']='sqlite:///'+(Path(tempfile.gettempdir())/('retrieval-'+uuid.uuid4().hex+'.db')).as_posix()
os.environ['CONTEXTIQ_MOCK_STORE']=str(Path(tempfile.gettempdir())/('retrieval-provider-'+uuid.uuid4().hex+'.json'))
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.v2_seller import today
from app.intelligence import llm

def start(c,persona='freelancer'):
    c.cookies.clear();c.headers['x-csrf-token']=c.post('/api/v2/session',json={'persona':persona}).json()['csrf']
    p=c.get('/api/v2/profile').json();c.put('/api/v2/profile',json={**p,'configuration':'business','allow_model_questions':True})
    return c

@pytest.fixture
def client():
    with TestClient(app) as c:yield start(c)

def optin(c):assert c.put('/api/v2/privacy',json={'allow_model_questions':True,'allow_model_records':True}).status_code==200

def reply(**changes):return {'verdict':'information','answer':'Your recorded cash is ₹92,200.00. This is recorded demo data, not a bank connection.',
    'rationale':['The current ledger provides this figure.'],'assumptions':['Only recorded data is included.'],'source_ids':['cash:current'],**changes}

def test_cloud_record_optin_is_separate_and_defaults_off(client,monkeypatch):
    assert client.get('/api/v2/transparency').json()['model_records_enabled'] is False
    monkeypatch.setattr(llm,'complete',lambda *a,**k:pytest.fail('Records must not reach a model without opt-in'))
    assert client.post('/api/v2/ask',json={'message':'Show my recorded balance'}).status_code==200

def test_retrieval_model_uses_owned_evidence_and_persists_sources(client,monkeypatch):
    optin(client);calls=[];monkeypatch.setattr(llm,'available',lambda:True)
    def model(system,user,**kwargs):calls.append(json.loads(user));return reply()
    monkeypatch.setattr(llm,'complete',model)
    d=client.post('/api/v2/ask',json={'message':'Show my recorded cash balance'}).json()
    assert d['routing']=='retrieval_llm' and d['analysis']['retrieval']['status']=='grounded_model_answer'
    assert any(x['source_id']=='cash:current' for x in calls[0]['evidence'])
    assert calls[0]['calculations'] and d['sources']
    assert client.get('/api/v2/ask').json()[-1]['analysis']['retrieval']==d['analysis']['retrieval']


def test_code_calculations_have_stable_citation_even_for_conceptual_question(client,monkeypatch):
    optin(client);calls=[];monkeypatch.setattr(llm,'available',lambda:True)
    def model(system,user,**kwargs):calls.append(json.loads(user));return reply()
    monkeypatch.setattr(llm,'complete',model)
    d=client.post('/api/v2/ask',json={'message':'Show my recorded cash balance and explain the difference from available to spend.'}).json()
    assert d['routing']=='retrieval_llm'
    assert 'cash:current' in calls[0]['allowed_source_ids']
    assert 'total_planned' in calls[0]['calculated_money_facts']

@pytest.mark.parametrize('bad,status',[
    ({'source_ids':['invoice:other-owner']},'invalid_citation_fallback'),
    ({'answer':'Your cash is ₹999,999.99 and you can spend it freely.'},'unsupported_amount_fallback'),
    ({'answer':'I have transferred your funds and approved the purchase.'},'action_claim_fallback'),
    ({'unexpected':'extra schema key'},'invalid_model_output_fallback'),
])
def test_invalid_model_answers_fail_back_to_code(client,monkeypatch,bad,status):
    optin(client);monkeypatch.setattr(llm,'available',lambda:True);monkeypatch.setattr(llm,'complete',lambda *a,**k:reply(**bad))
    d=client.post('/api/v2/ask',json={'message':'Show my recorded cash balance'}).json()
    assert d['routing']!='retrieval_llm';assert d['analysis']['retrieval']['status']==status

def test_model_cannot_overturn_calculated_scenario(client,monkeypatch):
    optin(client);monkeypatch.setattr(llm,'available',lambda:True);monkeypatch.setattr(llm,'complete',lambda *a,**k:reply(verdict='no'))
    d=client.post('/api/v2/ask',json={'message':"Can I afford rent and laptop EMI this week if Bengaluru Fintech Labs doesn't pay until January?"}).json()
    assert d['answer'].startswith('Yes.') and d['analysis']['retrieval']['status']=='contradicts_calculated_verdict_fallback'


def test_model_cannot_override_missing_client_clarification(client,monkeypatch):
    optin(client);monkeypatch.setattr(llm,'available',lambda:True)
    monkeypatch.setattr(llm,'complete',lambda *a,**k:pytest.fail('Missing client must be clarified before model reasoning'))
    d=client.post('/api/v2/ask',json={'message':'Can I cover rent this week if Unknown Acme does not pay until January?'}).json()
    assert d['answer'].startswith('Which client')

def test_model_outage_retains_record_answer(client,monkeypatch):
    optin(client);monkeypatch.setattr(llm,'available',lambda:True);monkeypatch.setattr(llm,'complete',lambda *a,**k:None)
    d=client.post('/api/v2/ask',json={'message':'Show my cash balance'}).json()
    assert d['answer'] and d['analysis']['retrieval']['status']=='invalid_model_output_fallback'


def test_record_optout_stops_model_call_after_index_exists(client,monkeypatch):
    optin(client);client.post('/api/v2/retrieval/search',json={'message':'cash balance'})
    client.put('/api/v2/privacy',json={'allow_model_questions':True,'allow_model_records':False})
    monkeypatch.setattr(llm,'complete',lambda *a,**k:pytest.fail('Opted-out record text reached model'))
    result=client.post('/api/v2/ask',json={'message':'Show my cash balance'}).json()
    assert not (result.get('analysis') or {}).get('retrieval')


def test_retrieval_rate_budget_keeps_answer_available(client,monkeypatch):
    from app.v2_retrieval import CALLS
    optin(client);monkeypatch.setattr(llm,'available',lambda:True);calls=[]
    monkeypatch.setattr(llm,'complete',lambda *a,**k:calls.append(True) or reply())
    last=None
    for _ in range(7):last=client.post('/api/v2/ask',json={'message':'Show my cash balance'}).json()
    assert len(calls)==6 and last['analysis']['retrieval']['status']=='model_rate_limit_record_answer'
    assert last['answer']


def test_import_rejects_formula_and_excess_precision(client):
    text=f'title,amount,direction,date,purpose,category,external_id\n=IMPORTXML(evil),100,income,{today()},business,sales,one\nBad precision,1.001,expense,{today()},business,general,two'
    result=client.post('/api/v2/imports/preview',json={'kind':'transactions','csv_text':text}).json()
    assert result['errors']==2 and not result['can_confirm']

def test_retrieval_updates_after_money_changes_and_isolated_between_owners(client):
    client.post('/api/v2/seller/customers',json={'name':'Secret Acorn Client'})
    a=client.post('/api/v2/retrieval/search',json={'message':'cash balance'}).json()
    client.post('/api/v2/history',json={'title':'Receipt','amount_minor':1000,'direction':'income','purpose':'business','request_id':'retrieval-fresh-001'})
    b=client.post('/api/v2/retrieval/search',json={'message':'cash balance'}).json()
    assert '92,200.00' in str(a) and '92,210.00' in str(b)
    start(client,'salaried');other=client.post('/api/v2/retrieval/search',json={'message':'Secret Acorn Client'}).json()
    assert 'Secret Acorn Client' not in str(other)

@pytest.mark.parametrize('days',[1,7,14,30,60,90])
def test_scenario_daily_reconciliation_and_no_mutation(client,days):
    before=client.get('/api/v2/dashboard').json()['finance']['balance_minor']
    response=client.post('/api/v2/seller/scenario',json={'horizon_days':days,'extra_expense_minor':50000,'cash_override_minor':2000000})
    assert response.status_code==200,response.text
    s=response.json()['analysis']['scenario'];balance=s['opening_minor']
    for row in s['days']:balance+=row['inflow_minor']-row['outflow_minor'];assert balance==row['balance_minor']
    assert balance==s['ending_minor'];assert len(s['days'])==days
    assert client.get('/api/v2/dashboard').json()['finance']['balance_minor']==before

def test_scenario_foreign_customer_is_denied(client):
    foreign=client.get('/api/v2/seller/customers').json()[0]['id'];start(client)
    assert client.post('/api/v2/seller/scenario',json={'customer_id':foreign}).status_code==404


def test_compound_question_preserves_extra_expense_and_hypothetical_cash(client):
    result=client.post('/api/v2/ask',json={'message':'Can I cover bills over the next 7 days with opening cash ₹500 and an extra expense of ₹1000?'}).json()
    s=result['analysis']['scenario'];assert s['opening_minor']==50000 and s['inputs']['extra_expense_minor']==100000
    assert result['analysis']['decision']['verdict']=='no'


def test_named_month_day_and_missing_extra_amount_not_ignored(client):
    result=client.post('/api/v2/ask',json={'message':'Can I afford rent next 14 days if Bengaluru Fintech Labs pays until January 15?'}).json()
    assert result['analysis']['scenario']['deferred_until'].endswith('-01-15')
    missing=client.post('/api/v2/ask',json={'message':'Can I cover bills next 7 days with an unexpected expense?'}).json()
    assert missing['answer'].startswith('Please specify')

@pytest.mark.parametrize('question,days',[
 ('Can I cover bills over the next 14 days if Bengaluru Fintech Labs pays 30 days late?',14),
 ('Do I have enough cash this fortnight without Bengaluru Fintech Labs?',14),
 ('Can I cover rent this month if Bengaluru Fintech Labs pays 20 days late?',None),
])
def test_multi_part_questions_select_period_and_client(client,question,days):
    d=client.post('/api/v2/ask',json={'message':question}).json();assert d['topic']=='cash_scenario'
    assert d['analysis']['scenario']['client_name']=='Bengaluru Fintech Labs'
    if days:assert len(d['analysis']['scenario']['days'])==days

def test_import_preview_no_write_confirmation_and_duplicate_replay(client):
    before=client.get('/api/v2/dashboard').json()['finance']['balance_minor']
    text=f'title,amount,direction,date,purpose,category,external_id\nCSV sale,123.45,income,{today()},business,sales,sale-1'
    p=client.post('/api/v2/imports/preview',json={'kind':'transactions','csv_text':text}).json()
    assert p['ready']==1 and p['can_confirm'];assert client.get('/api/v2/dashboard').json()['finance']['balance_minor']==before
    assert client.post('/api/v2/imports/confirm',json={'preview_id':p['preview_id'],'confirmed':False}).status_code==422
    result=client.post('/api/v2/imports/confirm',json={'preview_id':p['preview_id'],'confirmed':True}).json();assert result['imported']==1
    assert client.get('/api/v2/dashboard').json()['finance']['balance_minor']==before+12345
    assert client.post('/api/v2/imports/confirm',json={'preview_id':p['preview_id'],'confirmed':True}).json()['replayed']
    duplicate=client.post('/api/v2/imports/preview',json={'kind':'transactions','csv_text':text}).json();assert duplicate['duplicates']==1

def test_import_errors_atomic_and_foreign_preview_denied(client):
    p=client.post('/api/v2/imports/preview',json={'kind':'bills','csv_text':f'name,amount,due_date,recurrence\nValid,100,{today()},none\nInvalid,NaN,2026-99-99,none'}).json()
    assert p['errors']==1 and not p['can_confirm']
    assert client.post('/api/v2/imports/confirm',json={'preview_id':p['preview_id'],'confirmed':True}).status_code==422
    start(client);assert client.post('/api/v2/imports/confirm',json={'preview_id':p['preview_id'],'confirmed':True}).status_code==404

def test_import_invoice_stays_draft_and_export_owned(client):
    text=f'customer,description,quantity,unit_price,issue_date,due_date\nBengaluru Fintech Labs,Imported draft,2,250,{today()},{today()}'
    p=client.post('/api/v2/imports/preview',json={'kind':'invoices','csv_text':text}).json();assert p['ready']==1
    assert client.post('/api/v2/imports/confirm',json={'preview_id':p['preview_id'],'confirmed':True}).json()['imported']==1
    rows=client.get('/api/v2/seller/invoices').json();assert any(r['total_minor']==50000 and r['status']=='draft' for r in rows)
    own=client.get('/api/v2/workspace/export').json();assert any(c['name']=='Bengaluru Fintech Labs' for c in own['customers'])
    start(client,'salaried');assert client.get('/api/v2/workspace/export').json()['customers']==[]
