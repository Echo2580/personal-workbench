import json
import pytest
from fastapi.testclient import TestClient
from app.main import create_app


@pytest.fixture
def context(tmp_path):
    app=create_app(tmp_path/'data')
    client=TestClient(app,base_url='http://127.0.0.1:17843')
    token=client.get('/api/v1/bootstrap').json()['token']
    headers={'X-Workbench-Token':token,'Origin':'http://127.0.0.1:17843','Content-Type':'application/json'}
    return client,headers,tmp_path/'data'


def test_note_search_returns_saved_id_and_open_parameters(context):
    client,h,data_dir=context
    note=client.post('/api/v1/notes',headers=h,json={'text':'毕业设计 Note UNIQUE'}).json()['item']
    response=client.get('/api/v1/search',headers=h,params={'q':'note unique'})
    assert response.status_code==200
    body=response.json()
    assert body['total']==1
    group=next(g for g in body['groups'] if g['key']=='notes')
    assert group['items'][0]['id']==note['id']
    assert group['items'][0]['route']=='/'
    assert group['items'][0]['params']=={'note':note['id']}


def test_note_search_limited_and_deleted_notes_disappear(context):
    client,h,data_dir=context
    for i in range(7):
        client.post('/api/v1/notes',headers=h,json={'text':f'检索样例 {i}'})
    body=client.get('/api/v1/search',headers=h,params={'q':'检索样例'}).json()
    group=next(g for g in body['groups'] if g['key']=='notes')
    assert len(group['items'])==5
    deleted=group['items'][0]['id']
    assert client.delete('/api/v1/notes/'+deleted,headers=h).status_code==204
    body=client.get('/api/v1/search',headers=h,params={'q':'检索样例'}).json()
    assert all(i['id']!=deleted for g in body['groups'] for i in g['items'])


def test_bad_notes_file_does_not_hide_task_results(context):
    client,h,data_dir=context
    client.post('/api/v1/tasks',headers=h,json={'title':'仍可检索的任务'})
    (data_dir/'home').mkdir(exist_ok=True)
    (data_dir/'home/notes.json').write_text('{broken',encoding='utf8')
    response=client.get('/api/v1/search',headers=h,params={'q':'仍可检索'})
    assert response.status_code==200
    assert response.json()['groups'][0]['items'][0]['title']=='仍可检索的任务'


@pytest.mark.parametrize('payload',[
    {'lines':['兼容旧笔记','兼容旧笔记']},
    {'items':[{'text':'兼容旧笔记'},{'text':'兼容旧笔记'}]},
])
def test_legacy_note_ids_are_stable_between_search_and_open(context,payload):
    client,h,data_dir=context
    (data_dir/'home').mkdir(exist_ok=True)
    (data_dir/'home/notes.json').write_text(json.dumps(payload,ensure_ascii=False),encoding='utf8')
    result=client.get('/api/v1/search',headers=h,params={'q':'兼容旧笔记'}).json()
    found=next(g for g in result['groups'] if g['key']=='notes')['items']
    opened=client.get('/api/v1/notes',headers=h).json()['items']
    assert [item['id'] for item in found]==[item['id'] for item in opened]
    assert len({item['id'] for item in opened})==2
    # An edit persists the canonical IDs for all notes, preserving later links.
    assert client.put('/api/v1/notes/'+opened[0]['id'],headers=h,json={'text':'已编辑旧笔记'}).status_code==200
    assert client.get('/api/v1/notes',headers=h).json()['items'][1]['id']==opened[1]['id']


def test_wrong_notes_json_shape_does_not_break_task_search(context):
    client,h,data_dir=context
    client.post('/api/v1/tasks',headers=h,json={'title':'仍可检索的任务'})
    (data_dir/'home').mkdir(exist_ok=True)
    (data_dir/'home/notes.json').write_text('["unexpected list"]',encoding='utf8')
    response=client.get('/api/v1/search',headers=h,params={'q':'仍可检索'})
    assert response.status_code==200
    assert response.json()['groups'][0]['items'][0]['title']=='仍可检索的任务'
