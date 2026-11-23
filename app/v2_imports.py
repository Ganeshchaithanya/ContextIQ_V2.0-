"""Preview/confirm CSV imports and scoped exports. No upload can execute a payment."""
import csv,hashlib,io,json
from datetime import date,datetime,time,timedelta,UTC
from decimal import Decimal,InvalidOperation
from typing import Literal
from pydantic import BaseModel,Field,StrictBool
from sqlalchemy import select
from .models import LedgerEntry,now
from .v2 import router,session,db_dep,fail,WRITE_LOCK,aware
from .v2_models import PlanningRecord,Customer,SellerBill,SellerInvoice,SellerInvoiceLine
from fastapi import Depends

class CSVIn(BaseModel):
    kind:Literal['customers','bills','invoices','transactions']
    csv_text:str=Field(min_length=5,max_length=200000)

class ConfirmIn(BaseModel):
    preview_id:str=Field(min_length=8,max_length=100)
    confirmed:StrictBool

HEADERS={'customers':['name','email','phone','usual_payment_delay_days'],
         'bills':['name','amount','due_date','recurrence'],
         'invoices':['customer','description','quantity','unit_price','issue_date','due_date'],
         'transactions':['title','amount','direction','date','purpose','category','external_id']}

def amount(value):
    try:n=Decimal(str(value).replace(',',''))
    except InvalidOperation:raise ValueError('Use a decimal rupee amount')
    if not n.is_finite() or n<=0 or n>10000000 or n*100!=(n*100).to_integral_value():raise ValueError('Amounts must be positive with at most two decimal places')
    return int(n*100)

def normalize(kind,row):
    from .v2_seller import today
    d={str(k).strip():str(v or '').strip() for k,v in row.items() if k is not None}
    if any(len(x)>300 for x in d.values()):raise ValueError('A field is too long')
    for key in ('name','title','customer','description'):
        if key in d and d[key].startswith(('=','+','@','-')):raise ValueError('Formula-like text is not accepted')
    if kind=='customers':
        if not d.get('name'):raise ValueError('Customer name is required')
        delay=int(d.get('usual_payment_delay_days') or 0)
        if not 0<=delay<=120:raise ValueError('Delay must be 0–120 days')
        return {'name':d['name'],'email':d.get('email',''),'phone':d.get('phone',''),'usual_payment_delay_days':delay}
    if kind=='bills':
        if not d.get('name'):raise ValueError('Bill name is required')
        due=date.fromisoformat(d['due_date']);rec=d.get('recurrence') or 'none'
        if rec not in ('none','monthly'):raise ValueError('Recurrence must be none or monthly')
        return {'name':d['name'],'amount_minor':amount(d['amount']),'due_date':due.isoformat(),'recurrence':rec}
    if kind=='invoices':
        if not d.get('customer') or not d.get('description'):raise ValueError('Customer and description are required')
        due=date.fromisoformat(d['due_date']);issue=date.fromisoformat(d['issue_date']) if d.get('issue_date') else min(today(),due)
        qty=int(d.get('quantity') or 1);unit=amount(d['unit_price'])
        if due<issue or not 1<=qty<=10000 or qty*unit>1000000000:raise ValueError('Check dates, quantity and invoice total')
        return {'customer':d['customer'],'description':d['description'],'quantity':qty,'unit_price_minor':unit,'issue_date':issue.isoformat(),'due_date':due.isoformat()}
    if not d.get('title'):raise ValueError('Transaction title is required')
    direction=d.get('direction');purpose=d.get('purpose') or 'business'
    if direction not in ('income','expense') or purpose not in ('business','personal'):raise ValueError('Use income/expense and business/personal')
    return {'title':d['title'],'amount_minor':amount(d['amount']),'direction':direction,'date':date.fromisoformat(d['date']).isoformat(),
            'purpose':purpose,'category':d.get('category') or 'general','external_id':d.get('external_id','')}

def fingerprint(owner,kind,row):return 'imported:'+hashlib.sha256((owner+'|'+kind+'|'+json.dumps(row,sort_keys=True)).encode()).hexdigest()

@router.get('/imports/templates')
def templates(current=Depends(session)):
    return {'headers':HEADERS,'limits':{'rows':300,'characters':200000},'invoice_mode':'Each row becomes a single-line draft invoice; no invoice is sent and no receipt is assumed.'}

@router.post('/imports/preview')
def preview(body:CSVIn,current=Depends(session),db=Depends(db_dep)):
    reader=csv.DictReader(io.StringIO(body.csv_text.lstrip('\ufeff')))
    if not reader.fieldnames or len(set(reader.fieldnames))!=len(reader.fieldnames) or any(h not in HEADERS[body.kind] for h in reader.fieldnames):fail(422,'Use the supplied CSV column names without duplicates')
    rows=[];seen=set();valid=[]
    customers=list(db.scalars(select(Customer).where(Customer.owner_id==current.buyer_id)))
    for i,row in enumerate(reader,start=2):
        if len(rows)>=300:fail(422,'At most 300 rows per import')
        try:
            if None in row:raise ValueError('Too many columns')
            data=normalize(body.kind,row);key=fingerprint(current.buyer_id,body.kind,data)
            if body.kind=='invoices' and len([c for c in customers if c.name.casefold()==data['customer'].casefold()])!=1:raise ValueError('Choose an existing, unique customer name; import customers first')
            duplicate=key in seen or db.get(PlanningRecord,key) is not None
            if body.kind=='customers':duplicate=duplicate or any(c.name.casefold()==data['name'].casefold() for c in customers)
            rows.append({'line':i,'status':'duplicate' if duplicate else 'ready','data':data})
            if not duplicate:valid.append(data)
            seen.add(key)
        except (ValueError,KeyError,TypeError) as exc:rows.append({'line':i,'status':'error','error':str(exc)[:160]})
    if not rows:fail(422,'No data rows found')
    record=PlanningRecord(user_id=current.buyer_id,kind='import_preview',title=body.kind,
          data={'kind':body.kind,'rows':valid,'has_errors':any(r['status']=='error' for r in rows),'expires_at':(now()+timedelta(minutes=15)).isoformat(),'confirmed':False})
    db.add(record);db.commit()
    return {'preview_id':record.id,'kind':body.kind,'rows':rows,'ready':len(valid),'duplicates':sum(r['status']=='duplicate' for r in rows),
            'errors':sum(r['status']=='error' for r in rows),'can_confirm':bool(valid) and not record.data['has_errors'],
            'warning':'Only confirm records you have verified. Transactions change recorded cash; invoices are imported as drafts. No payment is executed.'}

@router.post('/imports/confirm')
def confirm(body:ConfirmIn,current=Depends(session),db=Depends(db_dep)):
    if not body.confirmed:fail(422,'Explicit confirmation is required')
    from .v2_seller import next_invoice_number
    with WRITE_LOCK:
        record=db.get(PlanningRecord,body.preview_id)
        if not record or record.user_id!=current.buyer_id or record.kind!='import_preview':fail(404,'Import preview not found')
        data=record.data
        if data.get('confirmed'):return data['result']|{'replayed':True}
        if data['has_errors'] or not data['rows']:fail(422,'Resolve preview errors before importing')
        if datetime.fromisoformat(data['expires_at'])<now():fail(409,'Preview expired. Preview the CSV again')
        customers=list(db.scalars(select(Customer).where(Customer.owner_id==current.buyer_id)))
        count=0;skipped=0
        for row in data['rows']:
            key=fingerprint(current.buyer_id,data['kind'],row)
            if db.get(PlanningRecord,key):skipped+=1;continue
            kind=data['kind']
            if kind=='customers':
                if any(c.name.casefold()==row['name'].casefold() for c in customers):skipped+=1;continue
                customer=Customer(owner_id=current.buyer_id,**row);db.add(customer);customers.append(customer)
            elif kind=='bills':db.add(SellerBill(owner_id=current.buyer_id,**{**row,'due_date':date.fromisoformat(row['due_date'])}))
            elif kind=='transactions':
                value=row['amount_minor']*(1 if row['direction']=='expense' else -1)
                db.add(LedgerEntry(user_id=current.buyer_id,payee=row['title'],description='Confirmed CSV import '+row['external_id'],
                    amount=value/100,amount_minor=value,currency='INR',purpose=row['purpose'],category=row['category'],source='csv_import',settlement_key=key,
                    occurred_at=datetime.combine(date.fromisoformat(row['date']),time(12),tzinfo=UTC)))
            else:
                matches=[c for c in customers if c.name.casefold()==row['customer'].casefold()]
                if len(matches)!=1:fail(409,'Customer changed since preview; preview again')
                invoice=SellerInvoice(owner_id=current.buyer_id,customer_id=matches[0].id,number=next_invoice_number(db,current.buyer_id),
                    issue_date=date.fromisoformat(row['issue_date']),due_date=date.fromisoformat(row['due_date']),total_minor=row['quantity']*row['unit_price_minor'],status='draft')
                db.add(invoice);db.flush();db.add(SellerInvoiceLine(invoice_id=invoice.id,description=row['description'],quantity=row['quantity'],unit_price_minor=row['unit_price_minor'],amount_minor=invoice.total_minor))
            db.add(PlanningRecord(id=key,user_id=current.buyer_id,kind='imported_row',title=kind,data={'imported_at':now().isoformat()}));db.flush();count+=1
        result={'imported':count,'skipped':skipped,'kind':data['kind'],'money_moved':False}
        record.data={**data,'confirmed':True,'result':result};db.commit();return result

@router.get('/workspace/export')
def export(current=Depends(session),db=Depends(db_dep)):
    from .v2 import bill_rows
    from .v2_seller import receivables_aging
    entries=db.scalars(select(LedgerEntry).where(LedgerEntry.user_id==current.buyer_id))
    return {'format':'ContextIQ owner-scoped export v1','exported_at':now().isoformat(),
            'customers':[{'name':r.name,'phone':r.phone,'email':r.email,'usual_payment_delay_days':r.usual_payment_delay_days} for r in db.scalars(select(Customer).where(Customer.owner_id==current.buyer_id))],
            'bills':bill_rows(db,current.buyer_id),'receivables':receivables_aging(current,db),
            'ledger':[{'title':r.payee,'description':r.description,'amount_minor':r.amount_minor,'currency':r.currency,'purpose':r.purpose,'category':r.category,'date':r.occurred_at.isoformat()} for r in entries],
            'warning':'This JSON export is not a complete database backup or an automatic restore package. Store it securely. It does not make free hosting durable.'}
