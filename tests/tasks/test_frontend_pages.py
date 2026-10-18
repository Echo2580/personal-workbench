"""T10 前端静态与 formMapping 纯函数测试。

formMapping 用本机 node 真实执行（app.js 中的纯函数区，非 Python 双写重放）。
集成可达性经 TestClient 走 HTTP。
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
# 静态可达与零外部资源
# ------------------------------------------------------------------

def test_index_page_served_and_links_local_assets(tmp_path):
    client = TestClient(create_app(tmp_path))

    page = client.get("/")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    text = page.text
    assert 'id="app"' in text
    assert 'src="/static/app.js"' in text
    assert 'href="/static/styles.css"' in text
    assert "#/tasks" in text
    for marker in (
        'id="view-list"',
        'id="view-detail"',
        'id="error-panel"',
        'id="task-list"',
        'id="task-form"',
    ):
        assert marker in text, marker


def test_static_js_and_css_served(tmp_path):
    client = TestClient(create_app(tmp_path))

    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert js.headers["content-type"].startswith(
        ("application/javascript", "text/javascript", "application/x-javascript")
    )
    assert "formMapping" in js.text
    assert "apiClient" in js.text

    css = client.get("/static/styles.css")
    assert css.status_code == 200


def test_no_external_resources_in_web_files():
    forbidden = re.compile(
        r"https?://|//cdn|unpkg|jsdelivr|cdnjs|googleapis|modao\.cc|tailwind|iconify"
    )
    for name in ("index.html", "styles.css", "app.js"):
        content = (WEB / name).read_text(encoding="utf-8")
        assert not forbidden.search(content), f"{name} 含外部资源引用"


def test_no_demo_data_in_frontend():
    # 产品名称来自用户原型，不属于演示数据；仍禁止种子任务和演示开关。
    banned = ["原型演示", "参加集合", "演示数据", "示例任务", "占位任务"]
    for name in ("index.html", "app.js"):
        content = (WEB / name).read_text(encoding="utf-8")
        for word in banned:
            assert word not in content, f"{name} 含演示痕迹：{word}"


@pytest.mark.parametrize("value", [
    "2026-10-20", "2026-10-20T09:30:00+08:00",
    "2026-10-20T09:30:45.123456+08:00", "",
])
def test_date_picker_round_trip_preserves_contract(value):
    """显示本地日期后不修改保存，不能改变日期精度、秒数、微秒或时区。"""
    node = shutil.which("node")
    if node is None:
        pytest.skip("本机无 node")
    script = "const fs=require('fs');(0,eval)(fs.readFileSync(process.argv[1],'utf8'));const v=process.argv[2];process.stdout.write(JSON.stringify(viewHelpers.toApiTime(viewHelpers.toLocalInput(v))));"
    result = subprocess.run([node, "-e", script, str(APP_JS), value], capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert json.loads(result.stdout) == value


# ------------------------------------------------------------------
# formMapping 真实执行（node）
# ------------------------------------------------------------------

_RUNNER = """
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const src = fs.readFileSync(process.argv[3], 'utf8');
const out = {};
try {
  (0, eval)(src);
  const fm = globalThis.formMapping;
  out.timeInfoFromForm = fm.timeInfoFromForm(input.timeinfoForm);
  out.timeInfoToForm = fm.timeInfoToForm(input.timeinfoJson);
  out.reminderFromForm = fm.reminderFromForm(input.reminderForm);
  out.reminderToForm = fm.reminderToForm(input.reminderJson);
  out.formToPatchBody = fm.formToPatchBody(input.patchForm, input.patchCurrent);
} catch (e) {
  out.__error = String(e && e.message ? e.message : e);
}
fs.writeFileSync(process.argv[4], JSON.stringify(out), 'utf8');
"""


def _run_form_mapping(
    timeinfo_form,
    timeinfo_json,
    reminder_form,
    reminder_json,
    patch_form,
    patch_current,
):
    node = shutil.which("node")
    if node is None:
        pytest.skip("本机无 node，无法真实执行 formMapping")
    with tempfile.TemporaryDirectory() as td:
        runner = Path(td) / "runner.js"
        input_file = Path(td) / "input.json"
        output_file = Path(td) / "output.json"
        runner.write_text(_RUNNER, encoding="utf-8")
        input_file.write_text(
            json.dumps(
                {
                    "timeinfoForm": timeinfo_form,
                    "timeinfoJson": timeinfo_json,
                    "reminderForm": reminder_form,
                    "reminderJson": reminder_json,
                    "patchForm": patch_form,
                    "patchCurrent": patch_current,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [node, str(runner), str(input_file), str(APP_JS), str(output_file)],
            capture_output=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        return json.loads(output_file.read_text(encoding="utf-8"))


def _check(out, key):
    assert "__error" not in out, out.get("__error")
    return out[key]


# ---- TimeInfo ----

def test_timeinfo_form_to_json_datetime():
    out = _run_form_mapping(
        {"enabled": True, "rawExpression": "10月20日10点", "precision": "datetime", "resolvedValue": "2026-10-20T10:00:00+08:00", "needsConfirmation": False},
        {"rawExpression": "10月20日10点", "precision": "datetime", "resolvedValue": "2026-10-20T10:00:00+08:00", "status": "resolved"},
        {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
        {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
        {},
        {},
    )
    assert _check(out, "timeInfoFromForm") == {
        "rawExpression": "10月20日10点",
        "precision": "datetime",
        "resolvedValue": "2026-10-20T10:00:00+08:00",
        "status": "resolved",
    }
    assert _check(out, "timeInfoToForm") == {
        "enabled": True,
        "rawExpression": "10月20日10点",
        "precision": "datetime",
        "resolvedValue": "2026-10-20T10:00:00+08:00",
        "needsConfirmation": False,
    }


def test_timeinfo_form_null_when_disabled():
    out = _run_form_mapping(
        {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        None,
        {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
        {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
        {},
        {},
    )
    assert _check(out, "timeInfoFromForm") is None
    assert _check(out, "timeInfoToForm") == {
        "enabled": False,
        "rawExpression": "",
        "precision": "date",
        "resolvedValue": "",
        "needsConfirmation": False,
    }


def test_timeinfo_form_needs_confirmation():
    out = _run_form_mapping(
        {"enabled": True, "rawExpression": "周五前", "precision": "relative", "resolvedValue": "", "needsConfirmation": True},
        {"rawExpression": "周五前", "precision": "relative", "resolvedValue": None, "status": "needs_confirmation"},
        {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
        {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
        {},
        {},
    )
    assert _check(out, "timeInfoFromForm") == {
        "rawExpression": "周五前",
        "precision": "relative",
        "resolvedValue": None,
        "status": "needs_confirmation",
    }
    assert _check(out, "timeInfoToForm")["needsConfirmation"] is True


def test_timeinfo_form_date_only_keeps_precision_date():
    out = _run_form_mapping(
        {"enabled": True, "rawExpression": "10月20日", "precision": "date", "resolvedValue": "2026-10-20", "needsConfirmation": False},
        {"rawExpression": "10月20日", "precision": "date", "resolvedValue": "2026-10-20", "status": "resolved"},
        {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
        {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
        {},
        {},
    )
    assert _check(out, "timeInfoFromForm")["precision"] == "date"
    assert _check(out, "timeInfoFromForm")["resolvedValue"] == "2026-10-20"


# ---- Reminder ----

def test_reminder_none_mode_matrix():
    out = _run_form_mapping(
        {"enabled": True, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        None,
        {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
        {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
        {},
        {},
    )
    assert _check(out, "reminderFromForm") == {
        "mode": "none",
        "requestedAt": None,
        "relativeTo": None,
        "offsetMinutes": None,
    }
    assert _check(out, "reminderToForm") == {
        "mode": "none",
        "requestedAt": "",
        "relativeTo": "",
        "offsetMinutes": "",
    }


def test_reminder_manual_mode_matrix():
    out = _run_form_mapping(
        {"enabled": True, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        None,
        {"mode": "manual", "requestedAt": "2026-10-20T09:00:00+08:00", "relativeTo": "", "offsetMinutes": ""},
        {"mode": "manual", "requestedAt": "2026-10-20T09:00:00+08:00", "relativeTo": None, "offsetMinutes": None},
        {},
        {},
    )
    assert _check(out, "reminderFromForm") == {
        "mode": "manual",
        "requestedAt": "2026-10-20T09:00:00+08:00",
        "relativeTo": None,
        "offsetMinutes": None,
    }


def test_reminder_relative_mode_matrix():
    out = _run_form_mapping(
        {"enabled": True, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        None,
        {"mode": "relative", "requestedAt": "", "relativeTo": "due", "offsetMinutes": "30"},
        {"mode": "relative", "requestedAt": None, "relativeTo": "due", "offsetMinutes": 30},
        {},
        {},
    )
    assert _check(out, "reminderFromForm") == {
        "mode": "relative",
        "requestedAt": None,
        "relativeTo": "due",
        "offsetMinutes": 30,
    }
    assert _check(out, "reminderToForm") == {
        "mode": "relative",
        "requestedAt": "",
        "relativeTo": "due",
        "offsetMinutes": "30",
    }


# ---- formToPatchBody（省略保持 / 显式 null 清空）----

def test_patch_body_omits_unchanged_fields():
    current = {
        "title": "交报告",
        "startTime": None,
        "dueTime": {"rawExpression": "10月20日", "precision": "date", "resolvedValue": "2026-10-20", "status": "resolved"},
        "requirements": ["打印"],
        "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "请于10月20日前交",
        "reminder": {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
    }
    # 表单只改了标题，其余字段原样（值与 current 相同 → 省略）
    form = {
        "title": "修改后的标题",
        "startTime": {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        "dueTime": {"enabled": True, "rawExpression": "10月20日", "precision": "date", "resolvedValue": "2026-10-20", "needsConfirmation": False},
        "requirementsText": "打印",
        "applicabilityStatus": "not_stated",
        "applicabilityText": "",
        "sourceExcerpt": "请于10月20日前交",
        "reminder": {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
    }
    out = _run_form_mapping(
        {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        None,
        {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
        {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
        form,
        current,
    )
    body = _check(out, "formToPatchBody")
    assert body == {"title": "修改后的标题"}, body  # 其余字段未变则省略


def test_patch_body_explicit_null_clears_time():
    current = {
        "title": "交报告",
        "startTime": None,
        "dueTime": {"rawExpression": "10月20日", "precision": "date", "resolvedValue": "2026-10-20", "status": "resolved"},
        "requirements": [],
        "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "请交",
        "reminder": {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
    }
    form = {
        "title": "交报告",
        "startTime": {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        "dueTime": {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        "requirementsText": "",
        "applicabilityStatus": "not_stated",
        "applicabilityText": "",
        "sourceExcerpt": "请交",
        "reminder": {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
    }
    out = _run_form_mapping(
        {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        None,
        {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
        {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
        form,
        current,
    )
    body = _check(out, "formToPatchBody")
    assert body == {"dueTime": None}, body


def test_patch_body_nested_object_full_replace():
    current = {
        "title": "交报告",
        "startTime": None,
        "dueTime": None,
        "requirements": ["打印"],
        "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": None,
        "reminder": {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
    }
    form = {
        "title": "交报告",
        "startTime": {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        "dueTime": {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        "requirementsText": "打印",
        "applicabilityStatus": "confirmed",
        "applicabilityText": "仅本班",
        "sourceExcerpt": None,
        "reminder": {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
    }
    out = _run_form_mapping(
        {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        None,
        {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
        {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
        form,
        current,
    )
    body = _check(out, "formToPatchBody")
    # 嵌套对象总是完整两键提交；applicability 变了 → 完整替换
    # O-01：sourceExcerpt 表单 null 且 current 也为 null → 省略
    assert body == {"applicability": {"text": "仅本班", "status": "confirmed"}}, body


def test_source_excerpt_null_clears_existing_text():
    """O-01：表单 null 而 current 有文本 → 提交显式 null（用户清空）。"""
    current = {
        "title": "交报告", "startTime": None, "dueTime": None,
        "requirements": [], "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "请于10月20日前交",
        "reminder": {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
    }
    form = {
        "title": "交报告",
        "startTime": {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        "dueTime": {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        "requirementsText": "", "applicabilityStatus": "not_stated", "applicabilityText": "",
        "sourceExcerpt": None,   # 用户清空
        "reminder": {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
    }
    out = _run_form_mapping(
        {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        None,
        {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
        {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
        form,
        current,
    )
    assert _check(out, "formToPatchBody") == {"sourceExcerpt": None}


def test_source_excerpt_null_and_null_is_omitted():
    """O-01：表单 null 且 current 也为 null → 省略（消除恒带 null 的副作用）。"""
    current = {
        "title": "交报告", "startTime": None, "dueTime": None,
        "requirements": [], "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": None,
        "reminder": {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
    }
    form = {
        "title": "交报告",
        "startTime": {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        "dueTime": {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        "requirementsText": "", "applicabilityStatus": "not_stated", "applicabilityText": "",
        "sourceExcerpt": None,
        "reminder": {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
    }
    out = _run_form_mapping(
        {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        None,
        {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
        {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
        form,
        current,
    )
    assert _check(out, "formToPatchBody") == {}


def test_source_excerpt_unchanged_is_omitted():
    """原文片段未改动（非空）→ 省略。"""
    current = {
        "title": "交报告", "startTime": None, "dueTime": None,
        "requirements": [], "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "请于10月20日前交",
        "reminder": {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
    }
    form = {
        "title": "交报告",
        "startTime": {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        "dueTime": {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        "requirementsText": "", "applicabilityStatus": "not_stated", "applicabilityText": "",
        "sourceExcerpt": "请于10月20日前交",
        "reminder": {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
    }
    out = _run_form_mapping(
        {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        None,
        {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
        {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
        form,
        current,
    )
    assert _check(out, "formToPatchBody") == {}


# ------------------------------------------------------------------
# P10-01 回归：current 含五键时间对象（含 timeZone）时不得误判为已变更
# ------------------------------------------------------------------

# 后端真实返回形状（五键）
FIVE_KEY_TIME = {
    "rawExpression": "10月20日10:00",
    "precision": "datetime",
    "resolvedValue": "2026-10-20T10:00:00+08:00",
    "timeZone": "Asia/Shanghai",
    "status": "resolved",
}

# 与之等价的表单形状（taskToForm 回填后用户未改动）
UNCHANGED_FORM_TIME = {
    "enabled": True,
    "rawExpression": "10月20日10:00",
    "precision": "datetime",
    "resolvedValue": "2026-10-20T10:00:00+08:00",
    "needsConfirmation": False,
}


def test_five_key_time_not_treated_as_changed():
    """P10-01 核心回归：只改 title 时 PATCH 体必须恰为 {title}。"""
    current = {
        "title": "交报告",
        "startTime": None,
        "dueTime": dict(FIVE_KEY_TIME),
        "requirements": ["打印纸质版"],
        "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "请于10月20日前交",
        "reminder": {"mode": "manual", "requestedAt": "2026-10-20T09:30:00+08:00",
                     "relativeTo": None, "offsetMinutes": None},
    }
    form = {
        "title": "交实验报告",
        "startTime": {"enabled": False, "rawExpression": "", "precision": "date",
                      "resolvedValue": "", "needsConfirmation": False},
        "dueTime": dict(UNCHANGED_FORM_TIME),
        "requirementsText": "打印纸质版",
        "applicabilityStatus": "not_stated",
        "applicabilityText": "",
        "sourceExcerpt": "请于10月20日前交",
        "reminder": {"mode": "manual", "requestedAt": "2026-10-20T09:30:00+08:00",
                     "relativeTo": "", "offsetMinutes": ""},
    }
    out = _run_form_mapping(
        {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        None,
        {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
        {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
        form,
        current,
    )
    body = _check(out, "formToPatchBody")
    assert body == {"title": "交实验报告"}, body


def test_five_key_start_time_also_normalized():
    """startTime 同样含五键时不得误判。"""
    current = {
        "title": "交报告",
        "startTime": dict(FIVE_KEY_TIME),
        "dueTime": None,
        "requirements": [],
        "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "请交报告",
        "reminder": {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
    }
    form = {
        "title": "交报告",
        "startTime": dict(UNCHANGED_FORM_TIME),
        "dueTime": {"enabled": False, "rawExpression": "", "precision": "date",
                    "resolvedValue": "", "needsConfirmation": False},
        "requirementsText": "",
        "applicabilityStatus": "not_stated",
        "applicabilityText": "",
        "sourceExcerpt": "请交报告",
        "reminder": {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
    }
    out = _run_form_mapping(
        {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        None,
        {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
        {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
        form,
        current,
    )
    assert _check(out, "formToPatchBody") == {}


def test_normalize_time_info_is_exported():
    """normalizeTimeInfo 必须存在且剥离 timeZone。"""
    content = APP_JS.read_text(encoding="utf-8")
    assert "normalizeTimeInfo" in content
    out = _run_form_mapping(
        {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
        None,
        {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
        {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
        {},
        {},
    )
    assert "__error" not in out


# ------------------------------------------------------------------
# P10-02：查看原文（text/plain 非 JSON 响应）
# ------------------------------------------------------------------

def test_source_content_endpoint_returns_text_plain(tmp_path):
    """后端 /content 对 text 源返回 text/plain（前端按此分支消费）。"""
    seed = {
        "id": "11111111-1111-4111-8111-111111111111",
        "kind": "text",
        "originalText": "请于10月20日10:00前交报告",
        "relativePath": None,
        "mimeType": "text/plain; charset=utf-8",
        "fileName": None,
        "messageDate": None,
        "importedAt": "2026-10-16T08:00:00+08:00",
        "contentSha256": "a" * 64,
    }
    from app.modules.tasks.storage import commit

    commit(tmp_path, lambda snap: snap.add_source_meta(seed))
    client = TestClient(create_app(tmp_path))

    response = client.get("/api/v1/sources/11111111-1111-4111-8111-111111111111/content")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.content.decode("utf-8") == "请于10月20日10:00前交报告"


def test_app_js_handles_non_json_response():
    """apiClient 必须支持非 JSON 响应（按 Content-Type 或 asText 分支）。"""
    content = APP_JS.read_text(encoding="utf-8")
    assert "Content-Type" in content
    assert "asText" in content
    assert "text/plain" in content


def test_source_content_error_path_still_parses_error_envelope(tmp_path):
    """图片源：文件缺失时错误包仍可解析 —— T11 起为 410 source_content_missing
    （原 T06 的 501 not_implemented 已被回收）。"""
    seed_img = {
        "id": "22222222-2222-4222-8222-222222222222",
        "kind": "image",
        "originalText": None,
        "relativePath": "data/sources/22222222-2222-4222-8222-222222222222.png",
        "mimeType": "image/png",
        "fileName": "note.png",
        "messageDate": None,
        "importedAt": "2026-10-16T08:00:00+08:00",
        "contentSha256": "b" * 64,
    }
    from app.modules.tasks.storage import commit

    commit(tmp_path, lambda snap: snap.add_source_meta(seed_img))
    client = TestClient(create_app(tmp_path))

    response = client.get("/api/v1/sources/22222222-2222-4222-8222-222222222222/content")

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "source_content_missing"


# ------------------------------------------------------------------
# P10-01 集成：保存后 revision 不变（有 scheduled 提醒）
# ------------------------------------------------------------------

def test_save_title_keeps_revision_integration(tmp_path):
    """有 scheduled 提醒的任务，只改标题保存后 revision 不得变化。"""
    from app.modules.tasks.storage import commit, load_snapshot

    source = {
        "id": "11111111-1111-4111-8111-111111111111",
        "kind": "text",
        "originalText": "请交报告",
        "relativePath": None,
        "mimeType": "text/plain; charset=utf-8",
        "fileName": None,
        "messageDate": None,
        "importedAt": "2026-10-16T08:00:00+08:00",
        "contentSha256": "a" * 64,
    }
    task = {
        "id": "aaaaaaaa-0000-4000-8000-000000000001",
        "draftId": "33333333-3333-4333-8333-333333333333",
        "sourceId": "11111111-1111-4111-8111-111111111111",
        "title": "交报告",
        "startTime": None,
        "dueTime": dict(FIVE_KEY_TIME),
        "requirements": [],
        "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "请交报告",
        "reviewIssues": [],
        "status": "open",
        "reminder": {
            "mode": "manual",
            "requestedAt": "2026-10-20T09:30:00+08:00",
            "scheduledAt": "2026-10-20T09:30:00+08:00",
            "relativeTo": None,
            "offsetMinutes": None,
            "state": "scheduled",
            "acknowledgedAt": None,
            "revision": "55555555-5555-4555-8555-555555555555",
        },
        "createdAt": "2026-10-16T08:00:00+08:00",
        "updatedAt": "2026-10-16T08:00:00+08:00",
    }
    commit(tmp_path, lambda snap: snap.add_source_meta(source).add_task(task))
    client = TestClient(create_app(tmp_path))

    before = client.get("/api/v1/tasks/aaaaaaaa-0000-4000-8000-000000000001").json()["task"]
    before_revision = before["reminder"]["revision"]
    assert before["reminder"]["state"] == "scheduled"

    # 只提交 title（等价于前端 formToPatchBody 的正确输出）
    patched = client.patch(
        "/api/v1/tasks/aaaaaaaa-0000-4000-8000-000000000001",
        json={"title": "交实验报告"},
    )

    assert patched.status_code == 200
    after = patched.json()["task"]
    assert after["title"] == "交实验报告"
    assert after["reminder"]["revision"] == before_revision
    assert after["reminder"]["state"] == "scheduled"
    assert after["reminder"]["scheduledAt"] == "2026-10-20T09:30:00+08:00"
