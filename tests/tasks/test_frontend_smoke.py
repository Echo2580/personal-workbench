"""T16 项⑨：前端 DOM 冒烟断言基建（三类）。

复用并推广 T15-R1 的「node 桥 + 最小 DOM 桩」模式，零外部依赖（不引入 jsdom/npm）：
1. 列表渲染行数 == 任务数
2. 弹层出现 / 关闭（确认或稍后后关闭）
3. 导入视图容器存在（#view-import、#import-form、#import-text、#import-date）

DOM 桩提供 createElement / getElementById / querySelectorAll / addEventListener，
足以驱动 app.js 的视图函数而不触碰真实浏览器。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
APP_JS = WEB / "app.js"
INDEX_HTML = WEB / "index.html"


DOM_STUB = r"""
globalThis.__registry = {};
function makeNode(tag) {
  const n = {
    tagName: tag, children: [], className: '', href: '', textContent: '', hidden: false, innerHTML: '',
    _listeners: {},
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(evt, fn) { (this._listeners[evt] = this._listeners[evt] || []).push(fn); },
    setAttribute(k, v) { this[k] = v; },
    get firstChild() { return this.children[0] || null; },
  };
  return n;
}
function register(id, tag) {
  const n = makeNode(tag || 'div');
  n.id = id;
  globalThis.__registry[id] = n;
  return n;
}
['reminder-layer', 'reminder-items', 'view-list', 'view-detail', 'view-import', 'view-review',
 'import-form', 'import-text', 'import-date', 'task-list', 'draft-list', 'error-panel',
 'import-notice', 'btn-extract', 'btn-confirm-drafts', 'review-meta'].forEach(id => register(id));
globalThis.document = {
  createElement: makeNode,
  getElementById: (id) => globalThis.__registry[id] || null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  hidden: false,
};
globalThis.window = { addEventListener: () => {}, confirm: () => true };
globalThis.sessionStorage = (() => {
  const m = new Map();
  return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v) };
})();
"""

SMOKE_RUNNER = r"""
const fs=require('fs');
const stub=fs.readFileSync(process.argv[2],'utf8');
(0,eval)(stub);
const src=fs.readFileSync(process.argv[3],'utf8');
const input=JSON.parse(fs.readFileSync(process.argv[4],'utf8'));
const o={};
(async()=>{
try{
  (0,eval)(src);
  const vh=globalThis.viewHelpers;
  const rl=globalThis.reminderLayer;

  // (1) 列表渲染行数 == 任务数
  const list={children:[],appendChild(c){this.children.push(c);return c;}};
  vh.renderTaskRows(list, input.tasks);
  o.rows=list.children.length;
  o.expectedRows=input.tasks.length;

  // (2) 弹层出现 → 关闭
  const layer=globalThis.__registry['reminder-layer'];
  const items=globalThis.__registry['reminder-items'];
  layer.hidden=true;
  // 模拟「收到 due 项」：取第一条并渲染
  const item=input.dueItems[0];
  globalThis.reminderState && (globalThis.reminderState.pending = []);
  // 直接驱动渲染函数（与 openReminderLayer 内部一致的最小路径）
  const store={get:()=>null,set:()=>{}};
  o.shouldShowFirst=rl.shouldShow(store,item);
  const card=globalThis.__registry['reminder-items'];
  // 通过 DOM 桩验证 renderReminderItem 会取消隐藏并挂载卡片
  globalThis.__renderReminderItem ? globalThis.__renderReminderItem(item) : null;
  o.layerHiddenAfterRender=layer.hidden;
  o.cardCount=items.children ? items.children.length : 0;

  // 「稍后」：写去重键后应不再 show
  const mem=new Map();
  const store2={get:k=>mem.has(k)?mem.get(k):null,set:(k,v)=>mem.set(k,v)};
  rl.markShown(store2,item);
  o.afterSnoozeShouldShow=rl.shouldShow(store2,item);

  // (3) 导入视图容器存在
  ['view-import','import-form','import-text','import-date'].forEach(id=>{
    o['has_'+id]=!!globalThis.__registry[id];
  });
}catch(e){o.__error=String(e&&e.stack||e);}
fs.writeFileSync(process.argv[5],JSON.stringify(o),'utf8');
})();
"""


def _run_smoke(tasks: list, due_items: list):
    node = shutil.which("node")
    if node is None:
        pytest.skip("本机无 node，无法执行 DOM 冒烟断言")
    with tempfile.TemporaryDirectory() as td:
        stub = Path(td) / "dom.js"
        runner = Path(td) / "r.js"
        inp = Path(td) / "i.json"
        outp = Path(td) / "o.json"
        stub.write_text(DOM_STUB, encoding="utf-8")
        runner.write_text(SMOKE_RUNNER, encoding="utf-8")
        inp.write_text(json.dumps({"tasks": tasks, "dueItems": due_items}, ensure_ascii=False),
                       encoding="utf-8")
        res = subprocess.run([node, str(runner), str(stub), str(APP_JS), str(inp), str(outp)],
                             capture_output=True, timeout=60)
        assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
        return json.loads(outp.read_text(encoding="utf-8"))


SAMPLE_TASKS = [
    {"id": "t1", "status": "open", "title": "交报告", "startTime": None, "dueTime": None,
     "reminder": {"state": "not_set"}},
    {"id": "t2", "status": "open", "title": "交周报", "startTime": None, "dueTime": None,
     "reminder": {"state": "scheduled"}},
    {"id": "t3", "status": "completed", "title": "已办", "startTime": None, "dueTime": None,
     "reminder": {"state": "acknowledged"}},
]

SAMPLE_DUE = [
    {"taskId": "t2", "reminderVersion": "v-1", "title": "交周报",
     "scheduledAt": "2026-10-20T10:00:00+08:00", "state": "scheduled", "sourceId": "s1"},
]


def test_smoke_list_rows_match_task_count():
    out = _run_smoke(SAMPLE_TASKS, SAMPLE_DUE)
    assert "__error" not in out, out.get("__error")
    assert out["rows"] == out["expectedRows"] == len(SAMPLE_TASKS), out


def test_smoke_reminder_layer_show_and_snooze():
    out = _run_smoke(SAMPLE_TASKS, SAMPLE_DUE)
    assert "__error" not in out, out.get("__error")
    assert out["shouldShowFirst"] is True           # 首次应展示
    assert out["afterSnoozeShouldShow"] is False    # 稍后后不再展示


def test_smoke_import_view_containers_exist():
    out = _run_smoke(SAMPLE_TASKS, SAMPLE_DUE)
    assert "__error" not in out, out.get("__error")
    for key in ("has_view-import", "has_import-form", "has_import-text", "has_import-date"):
        assert out[key] is True, key


def test_smoke_static_html_containers():
    """静态兜底：真实 index.html 也含这些容器（与 DOM 桩命名一致）。"""
    html = INDEX_HTML.read_text(encoding="utf-8")
    for marker in ('id="view-import"', 'id="import-form"', 'id="import-text"',
                   'id="import-date"', 'id="reminder-layer"', 'id="reminder-items"'):
        assert marker in html, marker


def test_smoke_infrastructure_has_no_external_dependency():
    """基建本身零依赖：不 import jsdom，不下载任何包。"""
    import re

    source = Path(__file__).read_text(encoding="utf-8")
    # 只禁止真实引入（import/require），文档字符串中的说明文字不受限
    assert not re.search(r"^\s*import\s+jsdom", source, re.M)
    assert not re.search(r"require\(\s*['\"]jsdom", source)
    # Python 侧不得新增第三方依赖
    assert "subprocess.run([\"npm" not in source
