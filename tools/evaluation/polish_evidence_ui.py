"""Keep internal citation IDs and unrelated generic suggestions out of the main answer."""
from pathlib import Path
p=Path(__file__).resolve().parents[2]/'app/static/v2-pages.js';s=p.read_text(encoding='utf-8')
old='${row.analysis.decision.rationale.map(r=>`<li>${esc(r)}</li>`).join("")}'
new='${row.analysis.decision.rationale.filter(r=>!/^A duplicate evidence entry/i.test(r)).map(r=>`<li>${esc(r.replace(/\\s*\\(source_id:\\s*[^)]+\\)/gi, "").replace(/\\bsource_id:\\s*[^\\s,)]+/gi, ""))}</li>`).join("")}'
assert old in s;s=s.replace(old,new,1)
old='${row.analysis && row.topic !== "overview" ?';new='${row.analysis && row.topic !== "overview" && !row.analysis.retrieval ?';assert old in s;s=s.replace(old,new,1)
old='${row.analysis.retrieval.sources.map(s=>';new='${row.analysis.retrieval.sources.filter((s,i,all)=>all.findIndex(x=>x.destination===s.destination)===i).map(s=>';assert old in s;s=s.replace(old,new,1)
s=s.replace('} sources considered</p>','} evidence matches</p>',1)
p.write_text(s,encoding='utf-8')
print('Evidence UI now hides internal IDs, duplicate destinations and generic unrelated follow-ups')
