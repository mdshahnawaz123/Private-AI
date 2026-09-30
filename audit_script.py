"""Comprehensive audit script for Expo Design AI."""
import os
import re
import json
import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))

report = {
    "timestamp": datetime.datetime.utcnow().isoformat(),
    "project": "Expo Design AI — Private Engineering AI Platform",
    "sections": {}
}

# ── 1. Code metrics ─────────────────────────────────────────
py_files = []
for root, dirs, files in os.walk('.'):
    if '.git' in root or '__pycache__' in root or 'data' in root or '_checkpoints' in root:
        continue
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                lines = len(fh.readlines())
            py_files.append((path.replace(os.sep, '/'), lines))

py_files.sort(key=lambda x: -x[1])
total_lines = sum(f[1] for f in py_files)

report["sections"]["code_metrics"] = {
    "total_python_files": len(py_files),
    "total_lines": total_lines,
    "top_20_files": [{"file": f, "lines": l} for f, l in py_files[:20]],
    "files_over_500_lines": [f for f, l in py_files if l > 500],
}

# ── 2. API endpoints ───────────────────────────────────────
with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Count routes using simple string matching
app_get = content.count('@app.get(')
app_post = content.count('@app.post(')
app_put = content.count('@app.put(')
app_delete = content.count('@app.delete(')
api_v1_get = content.count('@api_v1.get(')
api_v1_post = content.count('@api_v1.post(')
api_v1_put = content.count('@api_v1.put(')
api_v1_delete = content.count('@api_v1.delete(')

total_app = app_get + app_post + app_put + app_delete
total_v1 = api_v1_get + api_v1_post + api_v1_put + api_v1_delete

report["sections"]["api_endpoints"] = {
    "app_routes": {"get": app_get, "post": app_post, "put": app_put, "delete": app_delete, "total": total_app},
    "api_v1_routes": {"get": api_v1_get, "post": api_v1_post, "put": api_v1_put, "delete": api_v1_delete, "total": total_v1},
    "total_endpoints": total_app + total_v1,
}

# ── 3. Module inventory ────────────────────────────────────
modules = {}
for d in ['core', 'knowledge', 'intelligence', 'engines', 'agents', 'services', 'worker', 'tests']:
    if os.path.isdir(d):
        count = 0
        lines = 0
        for f in os.listdir(d):
            if f.endswith('.py'):
                count += 1
                with open(os.path.join(d, f), 'r', encoding='utf-8', errors='ignore') as fh:
                    lines += len(fh.readlines())
        modules[d] = {"files": count, "lines": lines}

report["sections"]["module_inventory"] = modules

# ── 4. Security audit ──────────────────────────────────────
security_issues = []
for root, dirs, files in os.walk('.'):
    if '.git' in root or '__pycache__' in root or 'data' in root or '_checkpoints' in root:
        continue
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                for i, line in enumerate(fh, 1):
                    # Hardcoded IPs (excluding localhost)
                    if re.search(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', line) and '0.0.0.0' not in line and '127.0.0.1' not in line:
                        security_issues.append({"type": "hardcoded_ip", "file": path.replace(os.sep, '/'), "line": i, "detail": line.strip()[:80]})
                    # Hardcoded passwords
                    if re.search(r'password\s*=\s*["\']', line, re.IGNORECASE) and 'os.getenv' not in line and 'getenv' not in line:
                        security_issues.append({"type": "hardcoded_password", "file": path.replace(os.sep, '/'), "line": i, "detail": line.strip()[:80]})
                    # Bare except
                    if re.search(r'except\s*:', line):
                        security_issues.append({"type": "bare_except", "file": path.replace(os.sep, '/'), "line": i, "detail": line.strip()[:80]})

report["sections"]["security_audit"] = {
    "issues_found": len(security_issues),
    "issues": security_issues,
}

# ── 5. TODO/FIXME audit ────────────────────────────────────
todos = []
for root, dirs, files in os.walk('.'):
    if '.git' in root or '__pycache__' in root or 'data' in root or '_checkpoints' in root:
        continue
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                for i, line in enumerate(fh, 1):
                    if re.search(r'#.*(TODO|FIXME|HACK|XXX|BUG)', line, re.IGNORECASE):
                        todos.append({"file": path.replace(os.sep, '/'), "line": i, "detail": line.strip()})

report["sections"]["todo_fixme"] = {
    "count": len(todos),
    "items": todos,
}

# ── 6. Import audit ────────────────────────────────────────
import sys
sys.path.insert(0, '.')
modules_to_test = [
    'main', 'db', 'auth', 'config',
    'core.model_registry', 'core.orchestrator', 'core.observability',
    'knowledge.entities', 'knowledge.graph', 'knowledge.hub',
    'knowledge.provenance', 'knowledge.precedence', 'knowledge.extraction',
    'intelligence.retrieval', 'intelligence.reranker', 'intelligence.compliance',
    'intelligence.validation', 'intelligence.reports',
    'engines.ocr_engine', 'engines.layout_engine', 'engines.drawing_engine', 'engines.ifc_engine',
    'agents.tools', 'agents.runtime',
    'services.ingestion', 'services.bim_service',
    'worker.celery_app', 'worker.tasks',
    'tests.evaluation.eval_framework',
]

ok = []
failed = []
for mod in modules_to_test:
    try:
        __import__(mod)
        ok.append(mod)
    except Exception as e:
        failed.append({"module": mod, "error": str(e)[:100]})

report["sections"]["import_audit"] = {
    "total": len(modules_to_test),
    "passed": len(ok),
    "failed": len(failed),
    "failures": failed,
}

# ── 7. Database tables ─────────────────────────────────────
with open('db.py', 'r', encoding='utf-8') as f:
    db_content = f.read()
tables = re.findall(r'__tablename__\s*=\s*["\']([^"\']+)["\']', db_content)
report["sections"]["database"] = {
    "total_tables": len(tables),
    "tables": tables,
}

# ── 8. Git stats ───────────────────────────────────────────
import subprocess
try:
    result = subprocess.run(['git', 'log', '--oneline'], capture_output=True, text=True, timeout=10)
    commits = result.stdout.strip().split('\n')
    report["sections"]["git"] = {
        "total_commits": len(commits),
        "recent_commits": commits[:10],
    }
except Exception as e:
    report["sections"]["git"] = {"error": str(e)}

# ── 9. Dependencies ─────────────────────────────────────────
with open('requirements.txt', 'r', encoding='utf-8') as f:
    deps = [line.strip() for line in f if line.strip() and not line.startswith('#')]
report["sections"]["dependencies"] = {
    "total": len(deps),
    "packages": deps,
}

# ── 10. Architecture compliance ────────────────────────────
arch_checks = {
    "model_registry": os.path.exists('core/model_registry.py'),
    "orchestrator": os.path.exists('core/orchestrator.py'),
    "knowledge_hub": os.path.exists('knowledge/hub.py'),
    "hybrid_retrieval": os.path.exists('intelligence/retrieval.py'),
    "compliance_engine": os.path.exists('intelligence/compliance.py'),
    "validation_engine": os.path.exists('intelligence/validation.py'),
    "report_engine": os.path.exists('intelligence/reports.py'),
    "ocr_engine": os.path.exists('engines/ocr_engine.py'),
    "layout_engine": os.path.exists('engines/layout_engine.py'),
    "drawing_engine": os.path.exists('engines/drawing_engine.py'),
    "ifc_engine": os.path.exists('engines/ifc_engine.py'),
    "agent_runtime": os.path.exists('agents/runtime.py'),
    "agent_tools": os.path.exists('agents/tools.py'),
    "bim_service": os.path.exists('services/bim_service.py'),
    "ingestion_pipeline": os.path.exists('services/ingestion.py'),
    "observability": os.path.exists('core/observability.py'),
    "evaluation_framework": os.path.exists('tests/evaluation/eval_framework.py'),
    "docker_deployment": os.path.exists('docker-compose.yml'),
    "backup_script": os.path.exists('backup.sh'),
}
report["sections"]["architecture_compliance"] = {
    "checks": arch_checks,
    "implemented": sum(1 for v in arch_checks.values() if v),
    "total": len(arch_checks),
}

# ── Write report ───────────────────────────────────────────
report_path = "AUDIT_REPORT.json"
with open(report_path, 'w', encoding='utf-8') as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

print("Audit report written to", report_path)
print()
print("=== AUDIT SUMMARY ===")
print("Total Python files:", report["sections"]["code_metrics"]["total_python_files"])
print("Total lines of code:", report["sections"]["code_metrics"]["total_lines"])
print("Total API endpoints:", report["sections"]["api_endpoints"]["total_endpoints"])
print("Database tables:", report["sections"]["database"]["total_tables"])
print("Modules imported OK:", report["sections"]["import_audit"]["passed"], "/", report["sections"]["import_audit"]["total"])
print("Security issues:", report["sections"]["security_audit"]["issues_found"])
print("TODO/FIXME:", report["sections"]["todo_fixme"]["count"])
print("Architecture checks passed:", report["sections"]["architecture_compliance"]["implemented"], "/", report["sections"]["architecture_compliance"]["total"])
print("Git commits:", report["sections"]["git"].get("total_commits", "N/A"))
print("Dependencies:", report["sections"]["dependencies"]["total"])
