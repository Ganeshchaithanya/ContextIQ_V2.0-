"""Read-only cash scenarios: validated inputs, owner-scoped records, daily arithmetic."""
import calendar
import re
from datetime import date,timedelta
from decimal import Decimal,InvalidOperation
from pydantic import BaseModel,Field
from sqlalchemy import select
from .v2_models import Customer,SellerBill

class ScenarioIn(BaseModel):
    horizon_days:int=Field(default=7,ge=1,le=90)
    customer_id:str|None=Field(default=None,max_length=64)
    delay_days:int=Field(default=0,ge=0,le=120)
    defer_until:date|None=None
    exclude_client_receipts:bool=False
    extra_expense_minor:int=Field(default=0,ge=0,le=1000000000)
    cash_override_minor:int|None=Field(default=None,ge=0,le=100000000000)

def is_cash_scenario(message):
    return bool(re.search(r'afford|cover|enough|cash|can (?:we|i) pay|run out|shortfall',message,re.I)
                and re.search(r'\bif\b|until|delay|late|without|next \d+|this (?:week|month)|fortnight|extra expense',message,re.I))

def evaluate(db,owner,plan):
    from .v2_seller import today,cash_position,open_invoices,bill_offsets,customers_by_id,rupees,owned
    from .v2_analysis import financial_analysis
    start=today();end=start+timedelta(days=plan.horizon_days)
    customers=customers_by_id(db,owner)
    client=owned(db,Customer,plan.customer_id,owner,'Customer not found') if plan.customer_id else None
    recorded=cash_position(db,owner,start);opening=recorded if plan.cash_override_minor is None else plan.cash_override_minor
    inflows=[0]*plan.horizon_days;outflows=[0]*plan.horizon_days;bills=[];records=[];deferred=0
    for bill in db.scalars(select(SellerBill).where(SellerBill.owner_id==owner)):
        if bill.paid:continue
        for offset in bill_offsets(bill.due_date,bill.recurrence,start,plan.horizon_days):
            outflows[offset]+=bill.amount_minor
            bills.append({'title':bill.name,'amount_minor':bill.amount_minor,'date':(start+timedelta(days=offset)).isoformat(),'destination':'#/seller/bills'})
    outflows[0]+=plan.extra_expense_minor
    for invoice in open_invoices(db,owner):
        customer=customers[invoice.customer_id];outstanding=invoice.total_minor-invoice.amount_paid_minor
        expected=max(invoice.due_date+timedelta(days=customer.usual_payment_delay_days),start)
        selected=client is not None and client.id==customer.id
        if selected:
            deferred+=outstanding
            expected=max(expected,plan.defer_until) if plan.defer_until else expected+timedelta(days=plan.delay_days)
            records.append({'label':invoice.number+' · '+customer.name,'value':rupees(outstanding),
                            'detail':'Excluded from the scenario.' if plan.exclude_client_receipts else f'Expected {expected} after the selected delay.',
                            'destination':'#/seller/invoices/'+invoice.id})
        if selected and plan.exclude_client_receipts:continue
        offset=(expected-start).days
        if 0<=offset<plan.horizon_days:inflows[offset]+=outstanding
    due=sum(outflows);conservative=opening-due;balance=opening;days=[]
    for i in range(plan.horizon_days):
        balance+=inflows[i]-outflows[i]
        days.append({'date':(start+timedelta(days=i)).isoformat(),'inflow_minor':inflows[i],'outflow_minor':outflows[i],'balance_minor':balance})
    minimum=min(days,key=lambda d:d['balance_minor']);negative=next((d['date'] for d in days if d['balance_minor']<0),None)
    verdict='yes' if conservative>=0 else 'uncertain' if not negative else 'no'
    assumptions=[f'The window is the next {plan.horizon_days} days, {start} through {end-timedelta(days=1)}, inclusive.',
                 'Only recorded business bills and open invoices are included. No new work, unrecorded spending or guaranteed receipts are assumed.',
                 'All recorded business bills due in this period are counted. Reserve and savings plans are separate from bill coverage.']
    if plan.defer_until:assumptions.append(f'No selected receipt is expected before {plan.defer_until}. An unspecified day in January or another month means its first day.')
    if plan.cash_override_minor is not None:assumptions.append(f'Hypothetical opening cash replaces recorded {rupees(recorded)} with {rupees(opening)} in this preview only.')
    answer=('Yes. ' if verdict=='yes' else 'Not from recorded cash alone. ')+f"You have {rupees(opening)} {'hypothetical' if plan.cash_override_minor is not None else 'recorded'} business cash and {rupees(due)} in bills and hypothetical expenses over the next {plan.horizon_days} days. Cash alone leaves {rupees(conservative)}. "
    if client:answer+=f"For {client.name}, I {'excluded' if plan.exclude_client_receipts else 'rescheduled'} {rupees(deferred)} in outstanding invoices. "
    answer+=('Bills included: '+'; '.join(f"{b['title']} {rupees(b['amount_minor'])} due {b['date']}" for b in bills)+'. ') if bills else 'No recorded bills fall in this period. '
    if plan.extra_expense_minor:answer+=f'Hypothetical extra expense: {rupees(plan.extra_expense_minor)}. '
    answer+=f"Expected receipts total {rupees(sum(inflows))}; projected ending cash is {rupees(balance)}. "
    answer+=f"The projection first goes negative on {negative}. " if negative else 'The scheduled projection stays at or above zero in this period. '
    if verdict=='uncertain':answer+='Coverage depends on uncertain customer receipts arriving on time. Confirm collection before committing. '
    answer+='This preview changes no records or payment dates. Payment remains your decision.'
    analysis=financial_analysis(db,owner,'cash_scenario')
    analysis['scenario']={'client_id':client.id if client else None,'client_name':client.name if client else 'No selected client',
        'start':start.isoformat(),'end_exclusive':end.isoformat(),'deferred_until':plan.defer_until.isoformat() if plan.defer_until else None,
        'deferred_minor':deferred,'recorded_opening_minor':recorded,'opening_minor':opening,'bills_minor':due,
        'cash_after_bills_minor':conservative,'other_receipts_minor':sum(inflows),'ending_minor':balance,
        'cash_alone_covers_bills':conservative>=0,'bills':bills,'days':days,'min_balance_minor':minimum['balance_minor'],
        'first_negative_date':negative,'inputs':plan.model_dump(mode='json'),'hypothetical':True}
    rationale=[f"{rupees(opening)} opening cash − {rupees(due)} bills/expenses = {rupees(conservative)} without any receipts.",
               f"Lowest scheduled day-end cash: {rupees(minimum['balance_minor'])} on {minimum['date']}; receipts are uncertain."]
    analysis['decision']={'verdict':verdict,'rationale':rationale,'assumptions':assumptions}
    analysis['assumptions']=assumptions+analysis['assumptions']
    analysis['calculations'].insert(0,{'label':'Requested client-delay scenario','expression':rationale[0]})
    analysis['records']=records+[{'label':b['title'],'value':rupees(b['amount_minor']),'detail':'Due '+b['date'],'destination':b['destination']} for b in bills]+analysis['records']
    analysis['next_step']=f"Review the {client.name} invoices and confirm collection." if client else 'Review the earliest negative date and upcoming bills.'
    analysis['limitations'].append('Scenario inputs are assumptions, not transactions. Inspect daily cash: an ending total can hide an earlier gap.')
    return {'topic':'cash_scenario','answer':answer,'destination':'#/seller/forecast','evidence':['authorized_ledger','seller_bills'],'analysis':analysis}

def clarify(text):return {'topic':'cash_scenario','answer':text,'destination':'#/seller/forecast','evidence':[]}

def cash_scenario(db,owner,message):
    from .v2_seller import today
    lower=message.lower();start=today();horizon=None
    match=re.search(r'next\s+(\d+)\s*(days?|weeks?)',lower)
    if match:horizon=int(match[1])*(7 if match[2].startswith('week') else 1)
    elif re.search(r'this week|next seven days',lower):horizon=7
    elif 'fortnight' in lower:horizon=14
    elif 'this month' in lower:horizon=calendar.monthrange(start.year,start.month)[1]-start.day+1
    if horizon is None or not 1<=horizon<=90:return clarify('What period should I check? Choose this week, this month, a fortnight or the next 1–90 days.')
    customers=list(db.scalars(select(Customer).where(Customer.owner_id==owner)))
    full=[c for c in customers if c.name.casefold() in lower]
    matched=full or [c for c in customers if re.search(r'\b'+re.escape(re.findall(r'\w+',c.name.lower())[0])+r'\b',lower)]
    conditional=bool(re.search(r'\bif\b|without|until|delay|late',lower))
    if conditional and len(matched)!=1:return clarify('Which client should I delay, and until what date? Use one unambiguous customer name or select an exact record in the scenario editor.')
    plan=ScenarioIn(horizon_days=horizon,customer_id=matched[0].id if len(matched)==1 else None)
    # Never silently ignore explicit hypothetical cash or an extra cost in a compound question.
    for field,marker,patterns in [
        ('extra_expense_minor',r'extra|unexpected|additional|one.off',[
            r'(?:extra|unexpected|additional|one.off)\s+(?:expense|cost|bill)(?:\s+of)?\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)',
            r'(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)\s+(?:extra|unexpected|additional)\s+(?:expense|cost|bill)']),
        ('cash_override_minor',r'hypothetical cash|opening cash|starting cash|only\s*(?:₹|rs\.?|inr)',[
            r'(?:hypothetical|opening|starting)\s+cash(?:\s+of)?\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)',
            r'only\s*(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)\s+(?:in\s+)?cash'])]:
        if not re.search(marker,lower):continue
        values=[m.group(1) for pattern in patterns for m in re.finditer(pattern,lower)]
        if len(values)!=1:return clarify('Please specify one hypothetical cash amount and one extra expense, or use the scenario editor to avoid guessing which amount belongs to which condition.')
        try:value=Decimal(values[0].replace(',',''))
        except InvalidOperation:return clarify('Use a valid rupee amount with at most two decimal places.')
        if value<0 or value>10000000 or value*100!=(value*100).to_integral_value():return clarify('Use a non-negative amount with at most two decimal places and at most ₹1,00,00,000.')
        setattr(plan,field,int(value*100))
    if conditional:
        delay=re.search(r'(\d+)\s*days?\s*(?:late|later)|(?:delay|late).*?(\d+)\s*days?',lower)
        iso=re.search(r'\b(20\d{2}-\d{2}-\d{2})\b',lower)
        month=next(((i,n) for i,n in enumerate(calendar.month_name) if i and re.search(r'\b'+n.lower()+r'\b',lower)),None)
        if delay:
            days=int(delay[1] or delay[2])
            if days>120:return clarify('Choose a client delay of 0–120 days.')
            plan.delay_days=days
        elif iso:
            try:plan.defer_until=date.fromisoformat(iso[1])
            except ValueError:return clarify('That date is invalid. Please use YYYY-MM-DD.')
        elif month:
            year=re.search(r'\b(20\d{2})\b',lower);year=int(year[1]) if year else start.year+(month[0]<start.month)
            day=re.search(r'\b(\d{1,2})\s+'+month[1].lower()+r'\b',lower) or re.search(r'\b'+month[1].lower()+r'\s+(\d{1,2})\b',lower)
            try:plan.defer_until=date(year,month[0],int(day[1]) if day else 1)
            except ValueError:return clarify('That calendar date is invalid. Please confirm the day, month and year.')
        elif 'without' not in lower:return clarify('How late will this client pay? Give a future date or a delay in days.')
        if plan.defer_until and plan.defer_until<start:return clarify('That delayed receipt date is in the past. Please confirm the future date.')
        plan.exclude_client_receipts='without' in lower or bool(plan.defer_until and plan.defer_until>=start+timedelta(days=horizon))
    return evaluate(db,owner,plan)
