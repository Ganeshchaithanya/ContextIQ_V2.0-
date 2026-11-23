"""Run existing checks in isolated processes; retain raw evidence and coverage."""
import json,os,subprocess,sys,time,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'reports'/'evaluation-2026-11-23';OUT.mkdir(parents=True,exist_ok=True)
env=os.environ.copy()
temp=OUT/'tmp';temp.mkdir(exist_ok=True)
env.update(TEMP=str(temp),TMP=str(temp),PAYPAL_ENV='mock',CONTEXTIQ_WORKER_MODE='off',GROQ_API_KEY='',ANTHROPIC_API_KEY='',COVERAGE_FILE=str(OUT/'.coverage'))
env.pop('POSTGRES_TEST_URL',None)
results=[]
for name in ['test_v2','test_seller','test_retrieval_imports','test_operations','test_experience','test_flows','test_postgres_operations']:
 env['CONTEXTIQ_LEGACY_TEST_AUTH']='1' if name=='test_flows' else '0'
 xml=OUT/(name+'.xml');start=time.perf_counter()
 cmd=[sys.executable,'-m','coverage','run','--branch','--parallel-mode','--source=app','-m','pytest','tests/'+name+'.py','-o','addopts=','-q','-p','no:cacheprovider','--junitxml='+str(xml)]
 p=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
 (OUT/(name+'.log')).write_text(p.stdout+p.stderr,encoding='utf-8')
 counts={k:0 for k in ['tests','failures','errors','skipped']}
 if xml.exists():
  for s in ET.parse(xml).getroot().iter('testsuite'):
   for k in counts:counts[k]+=int(s.attrib.get(k,0))
 result={'name':name,'exit_code':p.returncode,'seconds':round(time.perf_counter()-start,3),**counts}
 results.append(result);print(json.dumps(result),flush=True)
 p=None
cmd=['node','--test','tests/tour.test.cjs','tests/experience.test.cjs','tests/tara-widget.test.cjs']
start=time.perf_counter();p=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
(OUT/'javascript.log').write_text(p.stdout+p.stderr,encoding='utf-8')
import re
counts={key:int(re.search(r'(?:#|ℹ) '+key+r' (\d+)',p.stdout).group(1)) if re.search(r'(?:#|ℹ) '+key+r' (\d+)',p.stdout) else None for key in ['tests','pass','fail','skipped']}
results.append({'name':'javascript','exit_code':p.returncode,'seconds':round(time.perf_counter()-start,3),**counts})
print(json.dumps(results[-1]),flush=True)
for args in [['combine',str(OUT)],['json','-o',str(OUT/'coverage.json')]]:
 p=subprocess.run([sys.executable,'-m','coverage']+args,cwd=ROOT,env=env,capture_output=True,text=True)
 print(p.stdout.strip(),p.stderr.strip(),flush=True)
(OUT/'checks.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
