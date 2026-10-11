import os,sys,json,asyncio
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'output/remaining-release-checks-2026-10-10-final';DATA=OUT/'data'
os.chdir(ROOT);sys.path.insert(0,str(ROOT))
os.environ.update(EXPO_DATA_DIR=str(DATA),EXPO_DATABASE_URL='sqlite:///'+str(DATA/'expo.db'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
import main,db
import intelligence.answer_guard as guard
attempts=[];original=guard.guarded_answer
def capture(answer,evidence,sources):
    result=original(answer,evidence,sources)
    attempts.append({'answer':answer,'evidence':evidence,'sources':sources,'issues':result[1]})
    (OUT/'pressure-evidence-debug.json').write_text(json.dumps(attempts,indent=2),encoding='utf-8')
    return result
guard.guarded_answer=capture
async def run():
    request=SimpleNamespace(state=SimpleNamespace(user=db.get_user_by_username('admin')),headers={},client=SimpleNamespace(host='127.0.0.1'))
    response=await main.ask_stream(main.QueryRequest(project='SYNTH-A',query='What design pressure is specified for AHU-017?',focus_doc='Documents/native-a.pdf',messages=[],k=8),request)
    async for block in response.body_iterator:pass
asyncio.run(run())
