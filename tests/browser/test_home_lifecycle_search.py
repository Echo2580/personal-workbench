import json
import pytest
from playwright.sync_api import expect


def api(page,path,method='GET',body=None):
    return page.evaluate('''async({path,method,body})=>{
      const bootstrap=await(await fetch('/api/v1/bootstrap')).json();
      const response=await fetch('/api/v1'+path,{method,headers:{'X-Workbench-Token':bootstrap.token,'Content-Type':'application/json'},...(body===null?{}:{body:JSON.stringify(body)})});
      const data=await response.json();if(!response.ok)throw new Error(JSON.stringify(data));return data;
    }''',{'path':path,'method':method,'body':body})


def home(page):
    page.goto(page.url.split('#')[0]+'#/')
    expect(page.locator('#todoCard')).to_be_visible()
    page.wait_for_load_state('networkidle')


@pytest.mark.parametrize('route',['/projects','/tasks/import','/tasks','/settings'])
def test_global_search_after_cold_subpage_entry(ui,route):
    page,app,root=ui
    title='冷启动全局搜索唯一待办'
    api(page,'/tasks','POST',{'title':title})
    page.goto(page.url.split('#')[0]+'#'+route)
    page.reload(wait_until='networkidle')
    page.keyboard.press('Control+k')
    expect(page.locator('#globalSearch')).to_be_focused()
    page.locator('#globalSearch').fill(title)
    expect(page.locator('#searchResults button').filter(has_text=title)).to_have_count(1)


def test_home_unmount_removes_overlays_and_search_has_one_listener(ui):
    page,app,root=ui
    for _ in range(3):
        page.get_by_role('button',name='待办清单',exact=True).click()
        expect(page.locator('#view-list')).to_be_visible()
        expect(page.locator('#cityModal')).to_have_count(0)
        page.get_by_role('button',name='工作台首页',exact=True).click()
        expect(page.locator('#todoCard')).to_be_visible()
    expect(page.locator('#cityModal')).to_have_count(1)
    requests=[]
    page.on('request',lambda r:requests.append(r.url) if '/api/v1/search?q=' in r.url else None)
    page.locator('#globalSearch').fill('唯一一次搜索请求')
    page.wait_for_timeout(700)
    assert len(requests)==1,requests


@pytest.mark.parametrize('dismiss',['cancel','escape','backdrop'])
def test_cancel_entry_draft_never_changes_saved_entries(ui,dismiss):
    page,app,root=ui
    api(page,'/preferences','PUT',{'quickEntries':[{'label':'原有入口','url':'https://example.com/original'}]})
    page.reload(wait_until='networkidle')
    page.locator('#entriesCard').get_by_role('button',name='编辑',exact=True).click()
    page.locator('#manageList').get_by_role('button',name='删除入口 原有入口',exact=True).click()
    page.locator('#entryLabel').fill('取消的新入口')
    page.locator('#entryUrl').fill('https://example.com/discard')
    page.locator('#manageEntriesModal').get_by_role('button',name='添加',exact=True).click()
    if dismiss=='cancel':page.locator('#manageEntriesModal').get_by_role('button',name='取消',exact=True).click()
    elif dismiss=='escape':page.keyboard.press('Escape')
    else:page.locator('#manageEntriesModal').click(position={'x':2,'y':2})
    expect(page.locator('#manageEntriesModal')).not_to_be_visible()
    page.locator('#entriesCard').get_by_role('button',name='编辑',exact=True).click()
    expect(page.locator('#manageList')).to_contain_text('原有入口')
    expect(page.locator('#manageList')).not_to_contain_text('取消的新入口')
    saved=api(page,'/preferences')['quickEntries']
    assert [item['label'] for item in saved]==['原有入口']


def test_note_search_opens_and_focuses_matching_note_from_subpage(ui):
    page,app,root=ui
    title='查找这条独特的随手记'
    api(page,'/notes','POST',{'text':title})
    page.goto(page.url.split('#')[0]+'#/settings')
    page.reload(wait_until='networkidle')
    page.locator('#globalSearch').fill(title)
    hit=page.locator('#searchResults button').filter(has_text=title)
    expect(hit).to_have_count(1)
    hit.click()
    # 搜索结果直接打开随手记详情，展示完整内容（不再是列表抽屉）。
    modal=page.locator('#noteDetailModal')
    expect(modal).to_be_visible()
    expect(page.locator('#noteDetailModal .whitespace-pre-wrap')).to_have_text(title)
    page.keyboard.press('Escape')
    expect(modal).not_to_be_visible()
    # Clicking the same result must work even when the route already has its ID.
    page.locator('#globalSearch').fill(title)
    expect(hit).to_have_count(1)
    hit.click()
    expect(page.locator('#noteDetailModal')).to_be_visible()
    expect(page.locator('#noteDetailModal .whitespace-pre-wrap')).to_have_text(title)


def test_cleared_search_ignores_slow_response(ui):
    page,app,root=ui
    held=[]
    page.route('**/api/v1/search?*',lambda route:held.append(route))
    page.locator('#globalSearch').fill('会迟到的搜索词')
    page.wait_for_timeout(350)
    assert held
    page.locator('#globalSearch').fill('')
    for route in held:
        route.fulfill(status=200,content_type='application/json',body=json.dumps({'groups':[{'key':'tasks','items':[{'title':'不应重新出现','route':'/tasks'}]}]}))
    page.wait_for_timeout(350)
    expect(page.locator('#searchResults')).not_to_be_visible()
