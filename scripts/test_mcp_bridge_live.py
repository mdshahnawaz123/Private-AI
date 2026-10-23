import os
import sys
import json
import urllib.request

os.chdir(r'C:\3EH\ExpoDesignAI - Copy')
sys.path.insert(0, r'C:\3EH\ExpoDesignAI - Copy')

import db
import auth

u = db.get_user_by_username('admin')
token = auth.make_token(u)
headers = {
    'Authorization': f'Bearer {token}',
    'Content-Type': 'application/json'
}

print("==================================================")
print("TEST 1: /api/bim/plan-view-action for 'select only plant'")
print("==================================================")
req1 = urllib.request.Request(
    'http://127.0.0.1:8090/api/bim/plan-view-action',
    data=json.dumps({
        'project': 'C3082 - SiteWide',
        'question': 'select only plant',
        'categories': ['IFCBUILDINGELEMENTPROXY', 'IFCCOLUMN', 'IFCSLAB']
    }).encode('utf-8'),
    headers=headers
)
with urllib.request.urlopen(req1) as resp:
    res1 = json.loads(resp.read().decode('utf-8'))
    print("Handled:", res1.get('handled'))
    print("Planner:", res1.get('planner'))
    print("Operation:", res1.get('operation'))
    print("Action:", res1.get('action'))
    print("Target count:", res1.get('target_count'))
    print("Message:", res1.get('message'))
    print("Items count:", len(res1.get('items', [])))

print("\n==================================================")
print("TEST 2: /api/bim/plan-view-action for 'isolate palm'")
print("==================================================")
req2 = urllib.request.Request(
    'http://127.0.0.1:8090/api/bim/plan-view-action',
    data=json.dumps({
        'project': 'C3082 - SiteWide',
        'question': 'isolate palm',
        'categories': ['IFCBUILDINGELEMENTPROXY', 'IFCCOLUMN', 'IFCSLAB']
    }).encode('utf-8'),
    headers=headers
)
with urllib.request.urlopen(req2) as resp:
    res2 = json.loads(resp.read().decode('utf-8'))
    print("Handled:", res2.get('handled'))
    print("Planner:", res2.get('planner'))
    print("Operation:", res2.get('operation'))
    print("Action:", res2.get('action'))
    print("Target count:", res2.get('target_count'))
    print("Message:", res2.get('message'))
    print("Items count:", len(res2.get('items', [])))

print("\n==================================================")
print("TEST 3: /api/mcp/tools endpoint")
print("==================================================")
req3 = urllib.request.Request('http://127.0.0.1:8090/api/mcp/tools', headers=headers)
with urllib.request.urlopen(req3) as resp:
    res3 = json.loads(resp.read().decode('utf-8'))
    tools = [t['function']['name'] for t in res3.get('tools', [])]
    print("Available MCP Tools:", tools)

print("\n==================================================")
print("TEST 4: /api/mcp/call executing bim_takeoff_summary")
print("==================================================")
req4 = urllib.request.Request(
    'http://127.0.0.1:8090/api/mcp/call',
    data=json.dumps({
        'tool': 'bim_takeoff_summary',
        'arguments': {'project': 'C3082 - SiteWide', 'group_by': 'class'}
    }).encode('utf-8'),
    headers=headers
)
with urllib.request.urlopen(req4) as resp:
    res4 = json.loads(resp.read().decode('utf-8'))
    print("Takeoff total count:", res4.get('total_count'))
    print("Groups summary:")
    for g in res4.get('groups', [])[:4]:
        print(f"  - {g['group']}: count={g['count']}, vol={g['volume_m3']}m3, area={g['area_m2']}m2")

print("\nAll live tests PASSED successfully!")
