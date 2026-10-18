"""T15 提醒展示测试：轮询状态机、去重、确认三分支（纯逻辑经 node 执行），
静态结构与零外部资源为 Python 断言，集成走查经 TestClient + 真实服务。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tasks_test_app import create_app

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
APP_JS = WEB / "app.js"


# ------------------------------------------------------------------
# node 桥
# ------------------------------------------------------------------

_RUNNER = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const src = fs.readFileSync(process.argv[3], 'utf8');
const out = {};
try {
  (0, eval)(src);
  const rl = globalThis.reminderLayer;

  // ---- 去重键与判定 ----
  out.dedupeKey = rl.dedupeKey('task-1', 'ver-1');
  const memStore = (() => {
    const m = new Map();
    return { get: k => (m.has(k) ? m.get(k) : null), set: (k, v) => m.set(k, v) };
  })();
  const item = { taskId: 'task-1', reminderVersion: 'ver-1', title: 't' };
  out.firstShow = rl.shouldShow(memStore, item);
  rl.markShown(memStore, item);
  out.secondShow = rl.shouldShow(memStore, item);               // 同键 → false
  out.versionChanged = rl.shouldShow(memStore, { taskId: 'task-1', reminderVersion: 'ver-2', title: 't' });
  out.snoozeThenSkip = (() => {
    const s2 = (() => { const m = new Map(); return { get: k => (m.has(k) ? m.get(k) : null), set: (k, v) => m.set(k, v) }; })();
    rl.markShown(s2, item);          // 点「稍后」= 写去重键
    return rl.shouldShow(s2, item);  // 同会话不再弹
  })();

  // ---- 确认三分支 ----
  out.ackSuccess = rl.mapAckResult({ status: 200 });
  out.ackNetwork = rl.mapAckResult({ status: 0, code: 'network_error' });
  out.ackServer = rl.mapAckResult({ status: 500, code: 'storage_write_failed' });
  out.ackNotAcknowledgeable = rl.mapAckResult({ status: 409, code: 'reminder_not_acknowledgeable' });
  out.ackSuperseded = rl.mapAckResult({ status: 409, code: 'reminder_session_superseded' });
  out.ackVersionConflict = rl.mapAckResult({ status: 409, code: 'reminder_version_conflict' });

  (async () => {
  // ---- 轮询状态机（注入模拟 api / storage / visibility）----
  const calls = [];
  const fakeApi = {
    openSession: async () => { calls.push('open'); return { sessionId: 's1', startedAt: 'st', intervalSeconds: input.interval }; },
    due: async () => {
      calls.push('due');
      if (input.dueError) { const e = new Error('x'); e.status = input.dueError.status; e.code = input.dueError.code; throw e; }
      return { checkedAt: 'c', reminders: input.dueItems || [] };
    },
  };
  const poller = rl.createReminderPoller({
    api: fakeApi,
    visibility: { isHidden: () => input.hidden },
    onDue: items => calls.push('onDue:' + items.length),
    onSessionLost: () => calls.push('sessionLost'),
  });
  await poller.start();
  out.afterStart = calls.slice();
  // 手动推进 tick
  if (input.ticks) { for (let i = 0; i < input.ticks; i++) { await poller.tick(); } }
  out.afterTicks = calls.slice();
  out.interval = poller.intervalSeconds();
  })().catch(e => { out.__error = String(e && e.message ? e.message : e); });
} catch (e) {
  out.__error = String(e && e.message ? e.message : e);
}
setTimeout(() => {
  fs.writeFileSync(process.argv[4], JSON.stringify(out), 'utf8');
}, 50);
"""


def _run(data: dict):
    node = shutil.which("node")
    if node is None:
        pytest.skip("本机无 node，无法执行 app.js 纯逻辑")
    with tempfile.TemporaryDirectory() as td:
        runner = Path(td) / "r.js"
        inp = Path(td) / "i.json"
        outp = Path(td) / "o.json"
        runner.write_text(_RUNNER, encoding="utf-8")
        inp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        res = subprocess.run(
            [node, str(runner), str(inp), str(APP_JS), str(outp)],
            capture_output=True,
            timeout=30,
        )
        assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
        return json.loads(outp.read_text(encoding="utf-8"))


def ok(out):
    assert "__error" not in out, out.get("__error")
    return out


# ------------------------------------------------------------------
# 静态
# ------------------------------------------------------------------

def test_reminder_layer_container_and_copy_exist():
    text = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'id="reminder-layer"' in text
    assert "提醒仅在工具打开期间生效" in text


def test_reminder_layer_exports():
    content = APP_JS.read_text(encoding="utf-8")
    for fn in ("createReminderPoller", "dedupeKey", "shouldShow", "markShown", "mapAckResult"):
        assert re.search(rf"\b{fn}\b", content), f"缺 {fn}"


def test_no_external_resources_after_t15():
    forbidden = re.compile(
        r"https?://|//cdn|unpkg|jsdelivr|cdnjs|googleapis|modao\.cc|tailwind|iconify|Notification"
    )
    for name in ("index.html", "styles.css", "app.js"):
        content = (WEB / name).read_text(encoding="utf-8")
        assert not forbidden.search(content), f"{name} 含外部资源/Notification 引用"


def test_no_web_notification_api():
    content = APP_JS.read_text(encoding="utf-8")
    assert "Notification" not in content
    assert "webkitNotifications" not in content


# ------------------------------------------------------------------
# 去重
# ------------------------------------------------------------------

def test_dedupe_key_and_repeat_suppression():
    out = ok(_run({"interval": 5, "hidden": False, "ticks": 0, "dueItems": []}))
    assert out["dedupeKey"] == "task-1:ver-1"
    assert out["firstShow"] is True
    assert out["secondShow"] is False          # 同键不再弹
    assert out["versionChanged"] is True       # version 变化允许再弹
    assert out["snoozeThenSkip"] is False      # 「稍后」后同会话不再弹


# ------------------------------------------------------------------
# 确认三分支
# ------------------------------------------------------------------

def test_ack_success_closes_layer():
    out = ok(_run({"interval": 5, "hidden": False, "ticks": 0}))
    assert out["ackSuccess"]["action"] == "close"


def test_ack_unknown_shows_unknown_with_actions():
    out = ok(_run({"interval": 5, "hidden": False, "ticks": 0}))
    for key in ("ackNetwork", "ackServer"):
        assert out[key]["action"] == "unknown", key
        assert out[key]["retryable"] is True


def test_ack_not_acknowledgeable_refreshes():
    out = ok(_run({"interval": 5, "hidden": False, "ticks": 0}))
    assert out["ackNotAcknowledgeable"]["action"] == "refresh"


def test_ack_version_conflict_refreshes_and_closes():
    """P15-02：completed 任务换 revision 后确认旧版本 → version_conflict
    → refresh（刷新任务后关层，不伪装成功）。"""
    out = ok(_run({"interval": 5, "hidden": False, "ticks": 0}))
    assert out["ackVersionConflict"]["action"] == "refresh"
    assert out["ackVersionConflict"]["retryable"] is False


def test_app_js_no_undefined_due_reference():
    """P15-01 静态防护：行渲染函数内不得引用未定义的 due 变量。"""
    content = APP_JS.read_text(encoding="utf-8")
    start = content.index("renderTaskRows: function")
    end = content.index("return container;", start)
    body = content[start:end]
    assert "appendChild(due)" not in body
    assert "var time" in body          # 时间节点已定义
    assert "appendChild(time)" in body


def test_ack_other_conflicts():
    out = ok(_run({"interval": 5, "hidden": False, "ticks": 0}))
    # 会话取代/版本冲突：不伪装成功，按未知处理并提示刷新
    for key in ("ackSuperseded", "ackVersionConflict"):
        assert out[key]["action"] in ("unknown", "refresh"), key


# ------------------------------------------------------------------
# 轮询状态机
# ------------------------------------------------------------------

def test_poller_opens_session_once_and_ticks():
    out = ok(_run({"interval": 5, "hidden": False, "ticks": 2, "dueItems": []}))
    assert out["afterStart"].count("open") == 1
    assert out["afterTicks"].count("due") == 2
    assert out["interval"] == 5


def test_poller_pauses_when_hidden():
    out = ok(_run({"interval": 5, "hidden": True, "ticks": 3, "dueItems": []}))
    assert out["afterTicks"].count("due") == 0   # 隐藏 → 不执行
    assert "onDue:0" not in "".join(out["afterTicks"])


def test_poller_emits_items_and_skips_empty():
    out = ok(_run({
        "interval": 5, "hidden": False, "ticks": 1,
        "dueItems": [{"taskId": "t1", "reminderVersion": "v1", "title": "x"}],
    }))
    assert "onDue:1" in out["afterTicks"]

    out2 = ok(_run({"interval": 5, "hidden": False, "ticks": 1, "dueItems": []}))
    assert not [c for c in out2["afterTicks"] if c.startswith("onDue:")]  # 空轮询无 UI 回调


def test_poller_reopens_session_on_404_or_409():
    for status, code in ((404, "reminder_session_not_found"), (409, "reminder_session_superseded")):
        out = ok(_run({"interval": 5, "hidden": False, "ticks": 1,
                       "dueError": {"status": status, "code": code}}))
        assert "sessionLost" in out["afterTicks"], f"{code} 未触发重建"
        assert out["afterTicks"].count("open") >= 2


# ------------------------------------------------------------------
# 集成：真实服务 + 种子近未来提醒
# ------------------------------------------------------------------

def test_due_endpoint_returns_seeded_reminder(tmp_path):
    """种一个 scheduled 提醒，due 查询能返回它（供走查捕获）。"""
    from datetime import datetime, timedelta, timezone
    from app.modules.tasks.storage import commit

    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    scheduled = (now - timedelta(minutes=1)).isoformat()  # 已在区间内

    source = {
        "id": "11111111-1111-4111-8111-111111111111",
        "kind": "text", "originalText": "请交报告", "relativePath": None,
        "mimeType": "text/plain; charset=utf-8", "fileName": None,
        "messageDate": None, "importedAt": now.isoformat(), "contentSha256": "a" * 64,
    }
    task = {
        "id": "aaaaaaaa-0000-4000-8000-000000000001",
        "draftId": "33333333-3333-4333-8333-333333333333",
        "sourceId": "11111111-1111-4111-8111-111111111111",
        "title": "交报告", "startTime": None, "dueTime": None,
        "requirements": [], "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "请交报告", "reviewIssues": [], "status": "open",
        "reminder": {
            "mode": "manual", "requestedAt": scheduled, "scheduledAt": scheduled,
            "relativeTo": None, "offsetMinutes": None, "state": "scheduled",
            "acknowledgedAt": None, "revision": "55555555-5555-4555-8555-555555555555",
        },
        "createdAt": now.isoformat(), "updatedAt": now.isoformat(),
    }
    commit(tmp_path, lambda snap: snap.add_source_meta(source))
    client = TestClient(create_app(tmp_path))

    # 先开会话，用 session.startedAt 作为提醒时刻（区间含下界：startedAt <= scheduledAt）
    session = client.post("/api/v1/reminder-sessions").json()
    scheduled = session["startedAt"]

    task = {
        "id": "aaaaaaaa-0000-4000-8000-000000000001",
        "draftId": "33333333-3333-4333-8333-333333333333",
        "sourceId": "11111111-1111-4111-8111-111111111111",
        "title": "交报告", "startTime": None, "dueTime": None,
        "requirements": [], "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "请交报告", "reviewIssues": [], "status": "open",
        "reminder": {
            "mode": "manual", "requestedAt": scheduled, "scheduledAt": scheduled,
            "relativeTo": None, "offsetMinutes": None, "state": "scheduled",
            "acknowledgedAt": None, "revision": "55555555-5555-4555-8555-555555555555",
        },
        "createdAt": now.isoformat(), "updatedAt": now.isoformat(),
    }
    commit(tmp_path, lambda snap: snap.add_task(task))

    due = client.get(f"/api/v1/reminder-sessions/{session['sessionId']}/due").json()

    assert len(due["reminders"]) == 1
    item = due["reminders"][0]
    assert item["taskId"] == task["id"]
    assert item["reminderVersion"] == "55555555-5555-4555-8555-555555555555"
    assert item["state"] == "scheduled"
    assert session["intervalSeconds"] == 5


def test_acknowledge_flow_success(tmp_path):
    """确认成功 → state=acknowledged 且不再进入 due。"""
    from datetime import datetime, timedelta, timezone
    from app.modules.tasks.storage import commit

    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    scheduled = (now - timedelta(minutes=1)).isoformat()
    source = {
        "id": "11111111-1111-4111-8111-111111111111",
        "kind": "text", "originalText": "x", "relativePath": None,
        "mimeType": "text/plain; charset=utf-8", "fileName": None,
        "messageDate": None, "importedAt": now.isoformat(), "contentSha256": "a" * 64,
    }
    task = {
        "id": "aaaaaaaa-0000-4000-8000-000000000002",
        "draftId": "33333333-3333-4333-8333-333333333333",
        "sourceId": "11111111-1111-4111-8111-111111111111",
        "title": "交报告", "startTime": None, "dueTime": None,
        "requirements": [], "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "x", "reviewIssues": [], "status": "open",
        "reminder": {
            "mode": "manual", "requestedAt": scheduled, "scheduledAt": scheduled,
            "relativeTo": None, "offsetMinutes": None, "state": "scheduled",
            "acknowledgedAt": None, "revision": "55555555-5555-4555-8555-555555555555",
        },
        "createdAt": now.isoformat(), "updatedAt": now.isoformat(),
    }
    commit(tmp_path, lambda snap: snap.add_source_meta(source))
    client = TestClient(create_app(tmp_path))
    session = client.post("/api/v1/reminder-sessions").json()
    # 用 session.startedAt 作为提醒时刻（区间含下界 startedAt <= scheduledAt）
    scheduled = session["startedAt"]
    task["reminder"]["requestedAt"] = scheduled
    task["reminder"]["scheduledAt"] = scheduled
    commit(tmp_path, lambda snap: snap.add_task(task))

    ack = client.post(
        "/api/v1/reminders/aaaaaaaa-0000-4000-8000-000000000002/acknowledgment",
        json={"sessionId": session["sessionId"],
              "reminderVersion": "55555555-5555-4555-8555-555555555555"},
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["state"] == "acknowledged"

    due = client.get(f"/api/v1/reminder-sessions/{session['sessionId']}/due").json()
    assert due["reminders"] == []


def test_acknowledge_not_acknowledgeable_is_409(tmp_path):
    """未到期（晚于当前时间）→ 409 reminder_not_acknowledgeable。"""
    from datetime import datetime, timedelta, timezone
    from app.modules.tasks.storage import commit

    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    future = (now + timedelta(hours=2)).isoformat()
    source = {
        "id": "11111111-1111-4111-8111-111111111111",
        "kind": "text", "originalText": "x", "relativePath": None,
        "mimeType": "text/plain; charset=utf-8", "fileName": None,
        "messageDate": None, "importedAt": now.isoformat(), "contentSha256": "a" * 64,
    }
    task = {
        "id": "aaaaaaaa-0000-4000-8000-000000000003",
        "draftId": "33333333-3333-4333-8333-333333333333",
        "sourceId": "11111111-1111-4111-8111-111111111111",
        "title": "交报告", "startTime": None, "dueTime": None,
        "requirements": [], "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "x", "reviewIssues": [], "status": "open",
        "reminder": {
            "mode": "manual", "requestedAt": future, "scheduledAt": future,
            "relativeTo": None, "offsetMinutes": None, "state": "scheduled",
            "acknowledgedAt": None, "revision": "55555555-5555-4555-8555-555555555555",
        },
        "createdAt": now.isoformat(), "updatedAt": now.isoformat(),
    }
    commit(tmp_path, lambda snap: snap.add_source_meta(source).add_task(task))
    client = TestClient(create_app(tmp_path))
    session = client.post("/api/v1/reminder-sessions").json()

    ack = client.post(
        "/api/v1/reminders/aaaaaaaa-0000-4000-8000-000000000003/acknowledgment",
        json={"sessionId": session["sessionId"],
              "reminderVersion": "55555555-5555-4555-8555-555555555555"},
    )
    assert ack.status_code == 409
    assert ack.json()["error"]["code"] == "reminder_not_acknowledgeable"


def test_list_rows_equal_task_count():
    """P15-01 回归：有任务时列表行数 == 任务数（最小 DOM 桩 + node 桥）。

    选型：node 桥 + 最小 DOM 桩（不引入 jsdom/npm，保持零外部资源）。
    """
    dom_stub = r"""
    globalThis.document = (function () {
      function node(tag) {
        return {
          tagName: tag, children: [], className: '', href: '', textContent: '',
          appendChild: function (c) { this.children.push(c); return c; },
          setAttribute: function (k, v) { this[k] = v; },
          addEventListener: function () {},
        };
      }
      return {
        createElement: node,
        getElementById: function () { return null; },
        querySelectorAll: function () { return []; },
        addEventListener: function () {},
      };
    })();
    """
    runner = """
    const fs=require('fs');
    const stub=fs.readFileSync(process.argv[2],'utf8');
    (0,eval)(stub);
    const src=fs.readFileSync(process.argv[3],'utf8');
    const tasks=JSON.parse(fs.readFileSync(process.argv[4],'utf8'));
    const o={};
    (async()=>{
    try{
      (0,eval)(src);
      const vh=globalThis.viewHelpers;
      const container={children:[],appendChild(c){this.children.push(c);return c;}};
      vh.renderTaskRows(container, tasks);
      o.rows=container.children.length;
      o.firstRowChildren=container.children[0]?container.children[0].children.length:0;
      o.title=container.children[0]?container.children[0].children[1].children[0].textContent:null;
    }catch(e){o.__error=String(e&&e.message||e);}
    fs.writeFileSync(process.argv[5],JSON.stringify(o),'utf8');
    })();
    """
    tasks = [
        {"id": "t1", "status": "open", "title": "交报告",
         "startTime": None, "dueTime": None,
         "reminder": {"state": "not_set"}},
        {"id": "t2", "status": "open", "title": "交周报",
         "startTime": None, "dueTime": None,
         "reminder": {"state": "scheduled"}},
    ]
    node = shutil.which("node")
    if node is None:
        pytest.skip("本机无 node")
    with tempfile.TemporaryDirectory() as td:
        stub = Path(td) / "dom.js"
        r = Path(td) / "r.js"
        tf = Path(td) / "tasks.json"
        outp = Path(td) / "o.json"
        stub.write_text(dom_stub, encoding="utf-8")
        r.write_text(runner, encoding="utf-8")
        tf.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
        res = subprocess.run([node, str(r), str(stub), str(APP_JS), str(tf), str(outp)],
                             capture_output=True, timeout=30)
        assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
        out = json.loads(outp.read_text(encoding="utf-8"))

    assert "__error" not in out, out.get("__error")   # P15-01：未定义变量会抛错
    assert out["rows"] == len(tasks), out              # 行数 == 任务数
    assert out["firstRowChildren"] == 3                # 状态/任务内容/提醒与详情
    assert out["title"] == "交报告"


def test_poller_static_assertion_for_t15_layer():
    """弹层渲染函数为独立可测函数。"""
    content = APP_JS.read_text(encoding="utf-8")
    for fn in ("renderReminderItem", "submitAck", "openReminderLayer"):
        assert re.search(rf"\b{fn}\b", content), f"缺 {fn}"
