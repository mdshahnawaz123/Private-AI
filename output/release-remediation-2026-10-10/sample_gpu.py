import subprocess,time,json,os
from pathlib import Path
out=Path(__file__).resolve().parents[2]/'output'/os.environ.get('RELEASE_CHECK_OUTPUT','remaining-release-checks-2026-10-10')
samples=[]
for _ in range(600):
    result=subprocess.run(['nvidia-smi','--query-gpu=timestamp,name,memory.total,memory.used,utilization.gpu,temperature.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=10)
    samples.append({'time':time.time(),'returncode':result.returncode,'gpu':result.stdout.strip()})
    (out/'gpu-samples.json').write_text(json.dumps(samples,indent=2))
    if (out/'idempotence.json').exists():break
    time.sleep(2)
