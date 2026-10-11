"""Deterministic question-route load only. Not an OCR/model/upload capacity claim."""
import concurrent.futures
import json
from pathlib import Path
import statistics
import tempfile
import time
import psutil
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from intelligence.exact_answers import exact_answer
OUT=Path(__file__).parent
tempfile.tempdir=str(OUT/'tmp')
process=psutil.Process();results=[]
with tempfile.TemporaryDirectory() as directory:
    path=str(Path(directory)/'synthetic.pdf')
    Path(path+'.index.json').write_text(json.dumps({'pages':[{'page':1,'tables':
        '| ITEM | SQ.M. |\n| GFA Proposed: | 37.25 |\n| GFA Allowed: | 50 |'}]}))
    docs=[{'filename':'synthetic.pdf','path':path}]
    def ask(_):
        start=time.perf_counter()
        result=exact_answer('Is GFA proposed within GFA allowed?',docs)
        return (time.perf_counter()-start)*1000,result.get('calculation',{}).get('result')=='12.75'
    for concurrency in (4,8,16,32,64):
        before=process.cpu_times();rss_before=process.memory_info().rss;io_before=process.io_counters();start=time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            measurements=list(executor.map(ask,range(concurrency*2)))
        duration=time.perf_counter()-start;after=process.cpu_times();io_after=process.io_counters()
        latencies=sorted(m[0] for m in measurements)
        percentile=lambda p:latencies[min(len(latencies)-1,int((len(latencies)-1)*p))]
        results.append({'concurrency_limit':concurrency,'requests':len(measurements),'correct':sum(m[1] for m in measurements),
            'wall_seconds':duration,'latency_ms':{'p50':statistics.median(latencies),'p95':percentile(.95),'p99':percentile(.99)},
            'process_cpu_seconds':after.user+after.system-before.user-before.system,
            'rss_before_bytes':rss_before,'rss_after_bytes':process.memory_info().rss,
            'process_read_bytes':io_after.read_bytes-io_before.read_bytes,'process_write_bytes':io_after.write_bytes-io_before.write_bytes})
report={'scope':'Synthetic deterministic exact-answer route in this test process, not HTTP/server/OCR/vision/embedding/retrieval load',
        'not_measured':['peak RAM','GPU/VRAM','production queue depth','database contention','upload/OCR/vision/embedding capacity'],
        'results':results}
(OUT/'synthetic-load.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
