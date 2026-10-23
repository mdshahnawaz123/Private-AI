"""Guard against shipping a mismatched offline Fragments library and worker."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_fragments_browser_and_converter_versions_match():
    package = json.loads((ROOT / 'tools/fragments/package.json').read_text())
    lock = json.loads((ROOT / 'tools/fragments/package-lock.json').read_text())
    base = ROOT / 'ui/vendor_fragments/fragments'
    manifest = json.loads((base / 'version.json').read_text())
    version = package['dependencies']['@thatopen/fragments']
    assert manifest['version'] == version
    assert lock['packages']['node_modules/@thatopen/fragments']['version'] == version
    for name, expected in manifest['files'].items():
        content = (base / name).read_bytes()
        assert len(content) == expected['bytes']
        assert hashlib.sha256(content).hexdigest() == expected['sha256']
    viewer = (ROOT / 'ui/viewer_fragments.js').read_text(encoding='utf-8')
    page = (ROOT / 'ui/viewer.html').read_text(encoding='utf-8')
    assert f'index.mjs?v={version}' in viewer
    assert f'worker.mjs?v={version}' in viewer
    assert f'index.mjs?v={version}' in page
