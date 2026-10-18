import pytest
from playwright.sync_api import expect


def measure(page):
    return page.evaluate('''()=>{
      const rect=s=>{const r=document.querySelector(s).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}};
      return {viewport:{width:innerWidth,height:innerHeight},main:rect('#content'),workspace:rect('.wb-main'),home:rect('.home-page'),dashboard:rect('.home-dashboard'),footer:rect('.home-footnote'),bodyScrollHeight:document.scrollingElement.scrollHeight,bodyScrollWidth:document.scrollingElement.scrollWidth,mainScrollHeight:document.querySelector('#content').scrollHeight};
    }''')


@pytest.mark.parametrize('width,height',[(2550,1275),(1920,1080),(1440,900),(1280,720),(1024,768),(900,700),(600,800),(390,844)])
def test_home_fills_available_window_without_document_overflow(ui,width,height):
    page,app,root=ui
    page.set_viewport_size({'width':width,'height':height})
    expect(page.locator('#todoCard')).not_to_contain_text('正在读取待办…')
    size=measure(page)
    assert size['bodyScrollWidth']<=width
    assert size['bodyScrollHeight']<=height+1,'Application shell must fit the window; content owns scrolling'
    assert abs(size['main']['width']-size['workspace']['width'])<=1,'Main should use the available width'
    assert abs(size['home']['width']-size['main']['width'])<=1,'Home should use the available width'
    if width>=1024 and height>=720:
        assert size['footer']['bottom']<=size['main']['bottom']+1,'Desktop overview should fit at this size'
        assert size['main']['bottom']-size['footer']['bottom']<=24,'Overview should grow with window height'


def test_resizing_does_not_remount_home_or_lose_note_draft(ui):
    page,app,root=ui
    draft=page.get_by_label('随手记输入',exact=True)
    draft.fill('只用于窗口调整测试，尚未保存')
    for width,height in [(1920,1080),(900,650),(390,844),(1280,720)]:
        page.set_viewport_size({'width':width,'height':height})
        expect(draft).to_have_value('只用于窗口调整测试，尚未保存')
        expect(page.locator('#cityModal')).to_have_count(1)
    draft.scroll_into_view_if_needed()
    expect(draft).to_be_visible()


@pytest.mark.parametrize('width,height',[(1920,1080),(900,650),(390,844)])
def test_all_routes_stay_within_the_window(ui,width,height):
    page,app,root=ui
    page.set_viewport_size({'width':width,'height':height})
    for route in ['/projects','/tasks/import','/tasks','/settings']:
        page.goto(page.url.split('#')[0]+'#'+route)
        page.wait_for_load_state('networkidle')
        if route=='/projects':expect(page.get_by_role('heading',name='项目启动器',exact=True)).to_be_visible()
        elif route=='/tasks/import':expect(page.locator('#view-import')).to_be_visible()
        elif route=='/tasks':expect(page.locator('#view-list')).to_be_visible()
        else:expect(page.get_by_role('heading',name='扫描目录',exact=True)).to_be_visible()
        expect(page.locator('#globalSearch')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert page.evaluate('document.scrollingElement.scrollHeight<=innerHeight+1')
        assert page.evaluate('Math.abs(document.querySelector("#content").getBoundingClientRect().width-document.querySelector(".wb-main").getBoundingClientRect().width)<=1')
        page.locator('#content').evaluate('(node)=>node.scrollTop=node.scrollHeight')
        assert page.evaluate('document.querySelector("#content").getBoundingClientRect().bottom<=innerHeight+1')


@pytest.mark.parametrize('width,height',[(1280,520),(390,500)])
def test_short_window_can_scroll_to_last_card_without_moving_header(ui,width,height):
    page,app,root=ui
    page.set_viewport_size({'width':width,'height':height})
    page.get_by_label('随手记输入',exact=True).scroll_into_view_if_needed()
    expect(page.get_by_label('保存随手记',exact=True)).to_be_in_viewport()
    page.locator('.home-footnote').scroll_into_view_if_needed()
    expect(page.locator('.home-footnote')).to_be_in_viewport()
    assert page.evaluate('document.scrollingElement.scrollTop')==0
    assert page.locator('.wb-header').bounding_box()['y']>=0


def test_home_editing_dialogs_fit_a_short_browser_window(ui):
    page,app,root=ui
    page.set_viewport_size({'width':1280,'height':360})
    page.get_by_label('切换天气城市',exact=True).click()
    panel=page.locator('#cityModal > div')
    expect(panel).to_be_in_viewport(ratio=1)
    page.locator('#cityModal').get_by_role('button',name='查看',exact=True).scroll_into_view_if_needed()
    expect(page.locator('#cityModal').get_by_role('button',name='查看',exact=True)).to_be_in_viewport()
    page.keyboard.press('Escape')
    page.locator('#entriesCard').get_by_role('button',name='编辑',exact=True).click()
    expect(page.locator('#manageEntriesModal > div')).to_be_in_viewport(ratio=1)
    page.locator('#saveEntriesBtn').scroll_into_view_if_needed()
    expect(page.locator('#saveEntriesBtn')).to_be_in_viewport()
    page.keyboard.press('Escape')
    expect(page.locator('#manageEntriesModal')).not_to_be_visible()


def test_sidebar_actions_remain_reachable_in_short_window(ui):
    page,app,root=ui
    page.set_viewport_size({'width':1280,'height':300})
    expect(page.locator('#settings-nav')).to_be_in_viewport(ratio=1)
    expect(page.locator('#exit')).to_be_in_viewport(ratio=1)
    last=page.locator('#navigation').get_by_role('button',name='待办清单',exact=True)
    last.scroll_into_view_if_needed()
    expect(last).to_be_in_viewport(ratio=1)
    assert page.evaluate('document.scrollingElement.scrollTop')==0


@pytest.mark.parametrize('width,height',[(1280,360),(600,360)])
def test_search_last_result_remains_visible_in_short_window(ui,width,height):
    page,app,root=ui
    groups=[{'key':key,'label':key,'items':[{'title':f'视口测试结果 {base+i}','route':'/tasks'} for i in range(5)]} for key,base in [('projects',0),('tasks',5),('notes',10)]]
    page.route('**/api/v1/search?*',lambda route:route.fulfill(json={'groups':groups}))
    page.set_viewport_size({'width':width,'height':height})
    page.locator('#globalSearch').fill('视口测试')
    last=page.locator('#searchResults button').filter(has_text='视口测试结果 14')
    expect(last).to_have_count(1)
    results=page.locator('#searchResults')
    results.evaluate('(node)=>node.scrollTop=node.scrollHeight')
    expect(last).to_be_in_viewport(ratio=1)
    assert results.bounding_box()['y']+results.bounding_box()['height']<=height-8
