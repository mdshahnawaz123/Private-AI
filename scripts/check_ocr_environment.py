"""Read-only OCR dependency diagnosis. Does not import models or download weights."""
import json
import subprocess
import sys
from importlib.metadata import version, PackageNotFoundError


def inspect():
    names = ('paddleocr', 'paddlex', 'paddlepaddle', 'PyYAML', 'surya-ocr', 'Pillow', 'torch')
    installed = {}
    for name in names:
        try:
            installed[name] = version(name)
        except PackageNotFoundError:
            installed[name] = None
    check = subprocess.run([sys.executable, '-m', 'pip', 'check'], capture_output=True, text=True, timeout=60)
    return {'python': sys.executable, 'packages': installed,
            'dependency_check_passed': check.returncode == 0,
            'issues': (check.stdout + check.stderr).strip().splitlines(),
            'selected_backend': 'paddleocr', 'surya_app_integration': False,
            'note': 'Do not replace ComfyUI Torch or change the live shared environment to satisfy an unused OCR package. Provision and test the dedicated application environment first.'}


if __name__ == '__main__':
    result = inspect()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['dependency_check_passed'] else 1)
