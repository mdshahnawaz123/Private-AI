import os,sys,subprocess,json,re
from pathlib import Path
root=Path(__file__).resolve().parents[2];out=root/'output/remaining-release-checks-2026-10-10/suite';out.mkdir(parents=True,exist_ok=True)
results=[]
for path in sorted((root/'tests').glob('test_*.py')):
    runtime=out/path.stem;runtime.mkdir(exist_ok=True)
    env=dict(os.environ,EXPO_DATA_DIR=str(runtime),EXPO_DATABASE_URL='sqlite:///'+str(runtime/'test.db'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    code="import tempfile,unittest; tempfile.tempdir="+repr(str(runtime))+"; s=unittest.defaultTestLoader.discover('tests',pattern="+repr(path.name)+"); r=unittest.TextTestRunner(verbosity=2).run(s); raise SystemExit(not r.wasSuccessful())"
    result=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True,text=True,errors='replace',timeout=180)
    log=result.stdout+result.stderr;(out/(path.stem+'.log')).write_text(log,encoding='utf-8')
    count=re.search(r'Ran (\d+) tests?',log)
    row={'file':path.name,'returncode':result.returncode,'tests':int(count.group(1)) if count else None}
    results.append(row);(out/'results.json').write_text(json.dumps(results,indent=2));print(json.dumps(row),flush=True)
result=subprocess.run(['node','tests/test_stream_busy.js'],cwd=root,capture_output=True,text=True)
(out/'javascript.log').write_text(result.stdout+result.stderr)
print('JAVASCRIPT '+str(result.returncode),flush=True)
raise SystemExit(any(r['returncode'] for r in results) or result.returncode)
