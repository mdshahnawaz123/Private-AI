"""Non-production container acceptance checks; writes only a new output test folder."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.container_sandbox import find_container_engine, run_code_in_container


def main():
    root = Path(__file__).resolve().parents[1] / 'output' / 'audit-fixes-20261019' / ('worker-' + uuid.uuid4().hex)
    root.mkdir(parents=True)
    workspace = root / 'workspace'
    workspace.mkdir()
    (workspace / 'keep.txt').write_text('ORIGINAL')
    (workspace / 'delete.txt').write_text('ORIGINAL DELETE TARGET')
    (root / 'outside-canary.txt').write_text('PRIVATE TEST CANARY')
    started = time.monotonic()
    code = '''from pathlib import Path
import os, socket
assert os.getuid() == 1000
try:
    Path('/input/keep.txt').write_text('must fail')
    raise AssertionError('Input mount is writable')
except OSError:
    pass
assert not Path('/outside-canary.txt').exists()
s = socket.socket(); s.settimeout(.3)
try:
    s.connect(('192.0.2.1', 443))
    raise AssertionError('Unexpected network access')
except OSError:
    pass
finally:
    s.close()
Path('keep.txt').write_text('STAGED')
Path('delete.txt').unlink()
import pandas as pd
assert int(pd.Series([1, 2, 3]).sum()) == 6
Path('result.txt').write_text('6')
print('isolated task passed')
'''
    normal = run_code_in_container(code, workspace, timeout=30)
    assert normal['exit_code'] == 0, normal
    assert (workspace / 'keep.txt').read_text() == 'ORIGINAL'
    assert (workspace / 'delete.txt').is_file()
    assert normal['deleted_files'] == ['delete.txt'], normal
    timeout = run_code_in_container('import time; time.sleep(60)', workspace, timeout=2)
    assert timeout['exit_code'] == 124, timeout
    info = find_container_engine()
    remaining = subprocess.run([info['path'], 'ps', '-aq', '--filter', 'name=expo-task-' + timeout['run_id']],
                               capture_output=True, text=True, timeout=10)
    assert remaining.returncode == 0 and not remaining.stdout.strip(), remaining.stderr
    noisy = run_code_in_container("print('x' * 100000)", workspace, timeout=10)
    assert noisy['exit_code'] == 125, noisy['exit_code']
    assert len(noisy['stdout']) <= 65536
    summary = {'passed': True, 'seconds': round(time.monotonic() - started, 2),
               'normal': normal, 'timeout': timeout, 'output_limit': {**noisy, 'stdout': '[bounded output omitted]'}}
    (root / 'results.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({'passed': True, 'report': str(root / 'results.json'), 'seconds': summary['seconds']}))


if __name__ == '__main__':
    main()
