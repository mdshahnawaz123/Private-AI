import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from services.bim_action_planner import BimAction, BimPlan, plan_actions, simple_plan

CATS=['IFCDOOR','IFCWALLSTANDARDCASE','IFCCOLUMN']

def test_fast_commands_match_available_categories_and_preserve_scope():
    assert simple_plan('show only columns', CATS).actions[0].tool=='isolate'
    assert simple_plan('hide walls',CATS).actions[0].category=='IFCWALL'
    assert simple_plan('colour selected element red',CATS).actions[0].selected
    assert simple_plan('hide roofs',CATS) is None
    assert simple_plan('show only structural columns',CATS) is None
    assert simple_plan('colour fire doors red',CATS) is None
    assert simple_plan('hide walls and doors',CATS) is None

def test_tools_and_targets_are_closed_schema():
    for data in [{'tool':'run_code','code':'bad'}, {'tool':'color','category':'IFCDOOR'},
                 {'tool':'hide'}, {'tool':'reset','category':'IFCDOOR'},
                 {'tool':'color','selected':True,'color':'url(javascript:bad)'}]:
        with pytest.raises(ValidationError):BimAction.model_validate(data)
    with pytest.raises(ValidationError):BimPlan(actions=[BimAction(tool='fit')]*5)

def test_qwen_output_validated_and_offline_failure_is_not_success():
    response=AsyncMock()
    response.raise_for_status=lambda:None
    response.json=lambda:{'message':{'content':json.dumps({'actions':[{'tool':'hide','category':'IFCSECRET'}]})}}
    with patch('httpx.AsyncClient.post',return_value=response):
        result=asyncio.run(plan_actions('please conceal exterior walls',CATS))
    assert result['actions']==[] and 'error' in result
    with patch('httpx.AsyncClient.post',side_effect=RuntimeError('offline')):
        result=asyncio.run(plan_actions('conceal exterior walls',CATS))
    assert result['actions']==[] and result['handled']

def test_shortcut_does_not_require_model_network():
    with patch('httpx.AsyncClient.post',side_effect=AssertionError('must not call model')):
        assert asyncio.run(plan_actions('hide walls',CATS))['actions'][0]['tool']=='hide'

def test_authenticated_project_scope_and_cookie_command_api():
    import secrets
    import auth
    import db
    from main import app
    from fastapi.testclient import TestClient
    db.init_db()
    name='bim_tools_'+secrets.token_hex(4)
    password='Bim-qa-only-123!'
    user=db.create_user(name,auth.hash_password(password),role='user')
    with db.SessionLocal() as session:
        session.add(db.Project(name=name))
        session.commit()
    body={'project':name,'question':'hide doors','categories':CATS}
    with TestClient(app) as client:
        assert client.post('/api/bim/plan-view-action',json=body).status_code==401
        assert client.post('/auth/login',json={'username':name,'password':password}).status_code==200
        assert client.post('/api/bim/plan-view-action',json=body).status_code==403
        with patch('db.user_can_access',return_value=True):
            response=client.post('/api/bim/plan-view-action',json=body)
            assert response.status_code==200,response.text
            assert response.json()['actions'][0]['tool']=='hide'
            assert client.post('/api/bim/plan-view-action',json=body,headers={'Origin':'https://other.invalid'}).status_code==403
        assert client.post('/api/bim/plan-view-action',json={**body,'project':name+'_missing'}).status_code==404
