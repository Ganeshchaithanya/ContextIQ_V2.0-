"""Audit frozen artifacts without training or writing into app/ml/models."""
import hashlib,json,math,os,sys,time,warnings
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
OUT=ROOT/'reports'/'evaluation-2026-11-22';OUT.mkdir(parents=True,exist_ok=True)
os.environ['GROQ_API_KEY']=os.environ['ANTHROPIC_API_KEY']=''
os.environ['PAYPAL_ENV']='mock'
import joblib,numpy as np,pandas as pd
from sklearn import metrics as m
from app.config import MODEL_DIR
from app.ml import synth,redteam,runtime,policy_data
SEED=424242
def clean(x):
 if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
 if isinstance(x,(list,tuple,np.ndarray)):return [clean(v) for v in x]
 if isinstance(x,np.generic):return x.item()
 return x
def wilson(k,n):
 z=1.96;p=k/n;den=1+z*z/n;mid=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
 return [mid-half,mid+half]
def scores(y,p,proba=None,labels=None):
 y=np.array(y).astype(str);p=np.array(p).astype(str);labs=sorted(set(y)|set(p))
 d={'n':len(y),'accuracy':m.accuracy_score(y,p),'accuracy_wilson_95':wilson(int((y==p).sum()),len(y)),
 'balanced_accuracy':m.balanced_accuracy_score(y,p),'precision_macro':m.precision_score(y,p,average='macro',zero_division=0),
 'recall_macro':m.recall_score(y,p,average='macro',zero_division=0),'f1_macro':m.f1_score(y,p,average='macro',zero_division=0),
 'f1_weighted':m.f1_score(y,p,average='weighted',zero_division=0),'mcc':m.matthews_corrcoef(y,p),'cohen_kappa':m.cohen_kappa_score(y,p),
 'labels':labs,'confusion_matrix':m.confusion_matrix(y,p,labels=labs).tolist(),
 'per_class':m.classification_report(y,p,labels=labs,output_dict=True,zero_division=0)}
 if proba is not None:
  labels=np.array(labels).astype(str);confidence=proba.max(1);pred=labels[proba.argmax(1)];bins=[];ece=0
  for lo in np.arange(0,1,.1):
   mask=(confidence>=lo)&(confidence<(lo+.1) if lo<.9 else confidence<=1)
   if mask.any():
    acc=float((pred[mask]==y[mask]).mean());conf=float(confidence[mask].mean());ece+=abs(acc-conf)*mask.mean()
    bins.append({'low':float(lo),'n':int(mask.sum()),'accuracy':acc,'mean_confidence':conf})
  target=(y[:,None]==labels[None,:]).astype(float)
  d.update(log_loss=m.log_loss(y,proba,labels=labels),brier_multiclass=float(((proba-target)**2).sum(1).mean()),ece_10_bins=float(ece),calibration_bins=bins)
 return clean(d)
def latency(fn,n=40):
 fn();vals=[]
 for _ in range(n):
  t=time.perf_counter();fn();vals.append((time.perf_counter()-t)*1000)
 return {'n':n,'p50_ms':float(np.percentile(vals,50)),'p95_ms':float(np.percentile(vals,95)),'p99_ms':float(np.percentile(vals,99))}
def binary(y,p,raw=None):
 y=np.array(y).astype(int);p=np.array(p).astype(bool);tn,fp,fn,tp=m.confusion_matrix(y,p,labels=[0,1]).ravel()
 d={'n':len(y),'tn':tn,'fp':fp,'fn':fn,'tp':tp,'accuracy':m.accuracy_score(y,p),'precision':m.precision_score(y,p,zero_division=0),'recall':m.recall_score(y,p,zero_division=0),'f1':m.f1_score(y,p,zero_division=0),'specificity':tn/(tn+fp),'false_positive_rate':fp/(tn+fp),'false_negative_rate':fn/(tp+fn),'mcc':m.matthews_corrcoef(y,p),'balanced_accuracy':m.balanced_accuracy_score(y,p),'recall_wilson_95':wilson(tp,tp+fn),'precision_wilson_95':wilson(tp,tp+fp)}
 if raw is not None:d.update(roc_auc=m.roc_auc_score(y,raw),average_precision=m.average_precision_score(y,raw))
 return clean(d)
def main():
 warnings.filterwarnings('ignore',message='y_pred contains classes not in y_true')
 hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in MODEL_DIR.iterdir() if p.is_file()}
 res={'seed':SEED,'dataset_warning':'Synthetic generators reuse known template families. New seed is not independent real-world validation. Router final bank is reused, not fresh blind evaluation.','models':{}}
 def save(name,d):
  res['models'][name]=clean(d);(OUT/'models.json').write_text(json.dumps(clean(res),indent=2),encoding='utf-8');print(name,'completed',flush=True)
 from app.ml.unseen_questions import UNSEEN_FINAL
 texts=[t for group in UNSEEN_FINAL.values() for t in group];y=[label for label,group in UNSEEN_FINAL.items() for t in group]
 router=joblib.load(MODEL_DIR/'router.joblib');t=time.perf_counter();pr=router.predict_proba(texts);elapsed=time.perf_counter()-t
 save('legacy_router',{'dataset':'Existing 100-message final bank; explicitly reused','raw_model':scores(y,router.classes_[pr.argmax(1)],pr,router.classes_),'warm_latency':latency(lambda:runtime.route_intent('Can I return the faulty headphones?')),'batch_seconds':elapsed,'errors':[{'text':t,'truth':a,'prediction':str(b)} for t,a,b in zip(texts,y,router.classes_[pr.argmax(1)]) if a!=b]})
 users=synth.make_users(80,seed=SEED);tx=synth.make_transactions(users,seed=SEED,merchant_prefixes=synth._PREFIX_UNSEEN,night_business=.3)
 from app.ml.train import _tx_frame
 X=_tx_frame(tx)
 for target in ['purpose','category']:
  model=joblib.load(MODEL_DIR/(target+'_classifier.joblib'));t=time.perf_counter();proba=model.predict_proba(X);elapsed=time.perf_counter()-t;pred=model.classes_[proba.argmax(1)]
  result={'dataset':'80 synthetic users; unseen-prefix merchants; seed 424242','raw_model':scores(tx[target],pred,proba,model.classes_),'batch_seconds':elapsed,'rows_per_second':len(tx)/elapsed}
  if target=='purpose':
   mask=(tx.purpose=='business')&(tx.hour>=20);result['night_business_recall']=float((pred[mask]=='business').mean());result['night_business_n']=int(mask.sum())
  else:
   final=[]
   for (_,row),p,prob in zip(tx.iterrows(),pred,proba):final.append(runtime.category_from_keywords(f"{row.payee} {row.description}") or ('uncategorized' if max(prob)<runtime.CATEGORY_MIN_CONFIDENCE else p))
   result['runtime_with_keywords_and_abstention']=scores(tx[target],final);covered=np.array(final)!='uncategorized'
   result['runtime_coverage']=float(covered.mean());result['accuracy_on_covered']=float((np.array(final)[covered]==tx[target].to_numpy()[covered]).mean())
  save(target,result)
 normal=synth.normal_fraud_rows(19800,seed=SEED);families=redteam.TRAIN_FAMILIES+redteam.HELDOUT_FAMILIES
 attacks=pd.concat([redteam.attacks(f,40,seed=SEED+i,stealth=.3) for i,f in enumerate(families)])
 stream=pd.concat([normal,attacks],ignore_index=True);X=stream[synth.FRAUD_FEATURES];bundle=runtime._load('fraud');t=time.perf_counter()
 sup=bundle['supervised'].predict_proba(X)[:,1];anom=1/(1+np.exp(-12*-bundle['isolation'].decision_function(X)))
 urgent=X.urgency_score>=.5;changed=X.payee_changed_recently.astype(bool);new=X.new_payee.astype(bool)
 rule=np.minimum(1,.85*((urgent&(new|changed))|(X.urgency_score>.7))+.5*changed)
 sm=sup>=bundle['thresholds']['supervised'];am=anom>=bundle['thresholds']['anomaly'];rm=rule>=bundle['rule_threshold'];po=X.invoice_po_ratio>1.05
 model_flag=np.array(sm|am|rm);flag=np.array(model_flag|po);elapsed=time.perf_counter()-t
 indexes=np.r_[np.arange(10),np.arange(19800,19800+200,10)];parity=[]
 for idx in indexes:
  actual=runtime.fraud_score(X.iloc[idx].to_dict())['decision']!='allow';parity.append(actual==flag[idx])
 y=stream.label.to_numpy();d={'dataset':'20,000 synthetic payments, 1% attacks, 40 per family; stealth=.3','full_runtime':binary(y,flag),'model_layers_without_invoice_guard':binary(y,model_flag),'supervised_ranking':{'roc_auc':m.roc_auc_score(y,sup),'average_precision':m.average_precision_score(y,sup),'brier':m.brier_score_loss(y,sup)},'anomaly_ranking':{'roc_auc':m.roc_auc_score(y,anom),'average_precision':m.average_precision_score(y,anom)},'alerts_per_1000':float(flag.mean()*1000),'batch_seconds':elapsed,'parity_with_actual_runtime':{'passed':sum(parity),'n':len(parity)},'warm_latency':latency(lambda:runtime.fraud_score(X.iloc[0].to_dict()),20),'per_attack':{}}
 for f in families:
  mask=(stream.family==f).to_numpy();d['per_attack'][f]={'n':int(mask.sum()),'full_runtime_recall':float(flag[mask].mean()),'layers_without_invoice_guard_recall':float(model_flag[mask].mean())}
 save('fraud',d)
 df=synth.make_payee_series(3000,seed=SEED,utility_share=.35);sub=joblib.load(MODEL_DIR/'subscription.joblib');p=sub['model'].predict_proba(df[sub['features']])[:,1]
 save('subscription',{'dataset':'3,000 synthetic payee histories, 35% variable utilities','metrics':binary(df.label,p>=.5,p)})
 x,y=policy_data.make('unseen',100,seed=SEED);model=joblib.load(MODEL_DIR/'policy_tfidf.joblib')
 if isinstance(model,dict):model=model['model']
 probs=model.predict_proba(x);pred=model.classes_[probs.argmax(1)]
 save('policy_tfidf',{'dataset':'800 synthetic sentences from existing unseen style family, fresh seed','metrics':scores(y,pred,probs,model.classes_),'limitation':'Clause-type classification only; not extraction accuracy for days, exclusions, eligibility, or legal correctness. Optional LoRA cannot execute: torch and peft absent.'})
 from app.ml.forecast import CashFlowForecaster
 f=joblib.load(MODEL_DIR/'forecaster.joblib');daily=synth.make_daily_spend(n_users=80,seed=SEED);train=daily[daily.day<150];test=daily[daily.day>=150]
 g=CashFlowForecaster(profile=f.profile,shrink=f.shrink,range_scale=getattr(f,'range_scale',1)).fit(train)
 actual=[];pred=[];baseline=[];coverage=[];width=[];rows=[]
 for user,grp in test.groupby('user'):
  fc=g.forecast_user(user,30,150%7);a=grp.spend.sum();b=train[(train.user==user)&(train.day>=120)].spend.sum()
  actual.append(a);pred.append(fc['expected']);baseline.append(b);coverage.append(fc['p10']<=a<=fc['p90']);width.append(fc['p90']-fc['p10']);rows.append({'user':user,'actual':a,'prediction':fc['expected'],'baseline':b,'p10':fc['p10'],'p90':fc['p90']})
 actual=np.array(actual);pred=np.array(pred);baseline=np.array(baseline)
 save('forecast',{'dataset':'80 newly generated synthetic users, days <150 fitting and days 150–179 test; configuration unchanged','mae':m.mean_absolute_error(actual,pred),'rmse':math.sqrt(m.mean_squared_error(actual,pred)),'mape':float(np.mean(abs(pred-actual)/np.maximum(actual,1))),'wape':float(abs(pred-actual).sum()/abs(actual).sum()),'smape':float(np.mean(2*abs(pred-actual)/np.maximum(abs(pred)+abs(actual),1))),'r2':m.r2_score(actual,pred),'bias':float((pred-actual).mean()),'baseline_mape':float(np.mean(abs(baseline-actual)/np.maximum(actual,1))),'p10_p90_coverage':float(np.mean(coverage)),'nominal_coverage':.8,'mean_interval_width':float(np.mean(width)),'per_user':rows,'limitation':'Generated spending units; not INR validation. This learned forecast is distinct from current scheduled-invoice cash projection.'})
 from app.ml.evaluate_reasoning import _scenario,evaluate_bandit
 from app.intelligence.decision import decide,benchmark_order_invariance
 rng=np.random.default_rng(SEED);scenarios=[_scenario(rng) for _ in range(1000)];weights=json.loads((MODEL_DIR/'decision_weights.json').read_text())['weights'];y=[];p=[];stable=0;order=[]
 for i,(opts,truth) in enumerate(scenarios):
  chosen=(decide(opts,weights)['choice'] or {}).get('name');y.append(truth or 'none');p.append(chosen or 'none')
  if i<300:
   pert={k:v*rng.uniform(.8,1.2) for k,v in weights.items()};stable+=((decide(opts,pert)['choice'] or {}).get('name')==chosen)
  if i<100:
   shuffled=list(opts);rng.shuffle(shuffled);order.append((decide(shuffled,weights)['choice'] or {}).get('name')==chosen)
 save('decision',{'metrics':scores(y,p),'agreement_stability_20pct_weight_noise':stable/300,'option_order_invariance':sum(order)/len(order),'limitation':'Ground truth and option construction share hand-written policies. Consistency is not independent consumer-law validation.'})
 b=evaluate_bandit(seed=SEED,users=80,rounds=300);b['absolute_lift']=b['results']['Thompson sampling']-b['results']['fixed order'];b['relative_lift']=b['absolute_lift']/b['results']['fixed order'];b['limitation']='Simulated clicks only; not a real-user A/B test. Not proof that active V2 priorities use this bandit.';save('bandit',b)
 after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in MODEL_DIR.iterdir() if p.is_file()}
 res['artifact_hashes_unchanged']=hashes==after;res['artifact_sha256']=after
 (OUT/'models.json').write_text(json.dumps(clean(res),indent=2),encoding='utf-8');print('ALL FROZEN ARTIFACTS UNCHANGED',hashes==after,flush=True)
if __name__=='__main__':main()
