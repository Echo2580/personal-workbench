"""T09 导入与核对界面测试。

载荷形状与映射规则经 node 真实执行（web/app.js 纯函数区）；集成流程经
TestClient + MockExtractionModel 注入；静态结构/零外部资源为纯 Python 断言。
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
from app.modules.tasks.services.model_adapter import (
    MockExtractionModel,
    ModelOutputInvalidError,
    ModelTimeoutError,
    ModelUnavailableError,
)

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
APP_JS = WEB / "app.js"


# ------------------------------------------------------------------
# node 桥：执行 app.js 纯函数区
# ------------------------------------------------------------------

_RUNNER = """
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const src = fs.readFileSync(process.argv[3], 'utf8');
const out = {};
try {
  (0, eval)(src);
  const fm = globalThis.formMapping;
  out.extractionPayload = fm.buildExtractionPayload(input.originalText, input.messageDate);
  if (input.draftSet) {
    out.confirmationPayload = fm.buildConfirmationPayload(
      input.draftSet, input.originalText, input.drafts
    );
  }
  if (input.oomCurrentNull) {
    out.sourceExcerptNullNull = fm.formToPatchBody(input.oomFormNull, input.oomCurrentNull);
    out.sourceExcerptNullText = fm.formToPatchBody(input.oomFormNull, input.oomCurrentText);
  }
  out.errorText = globalThis.MODEL_ERROR_TEXT ? globalThis.MODEL_ERROR_TEXT[input.errorCode] : null;
  if (input.timeBoth) {
    out.timeColumnLabel = globalThis.viewHelpers
      ? globalThis.viewHelpers.timeColumnLabel(input.timeBoth)
      : null;
  }
  out.hasErrorTextTable = !!globalThis.MODEL_ERROR_TEXT;
} catch (e) {
  out.__error = String(e && e.message ? e.message : e);
}
fs.writeFileSync(process.argv[4], JSON.stringify(out), 'utf8');
"""


def _run(input_data: dict):
    node = shutil.which("node")
    if node is None:
        pytest.skip("本机无 node，无法真实执行 app.js 纯函数区")
    with tempfile.TemporaryDirectory() as td:
        runner = Path(td) / "runner.js"
        inp = Path(td) / "input.json"
        outp = Path(td) / "output.json"
        runner.write_text(_RUNNER, encoding="utf-8")
        inp.write_text(json.dumps(input_data, ensure_ascii=False), encoding="utf-8")
        res = subprocess.run(
            [node, str(runner), str(inp), str(APP_JS), str(outp)],
            capture_output=True,
            timeout=30,
        )
        assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
        return json.loads(outp.read_text(encoding="utf-8"))


def _ok(out):
    assert "__error" not in out, out.get("__error")
    return out


# 固定样本
ORIGINAL_TEXT = "请于10月20日10:00前交报告，需打印纸质版。"
DRAFT_SET = {
    "draftSetId": "dddddddd-0000-4000-8000-000000000001",
    "source": {
        "id": "11111111-1111-4111-8111-111111111111",
        "kind": "text",
        "mimeType": "text/plain; charset=utf-8",
        "fileName": None,
        "messageDate": None,
        "importedAt": "2026-10-16T08:00:00+08:00",
        "contentSha256": "a" * 64,
    },
    "status": "review",
    "drafts": [
        {
            "id": "eeeeeeee-0000-4000-8000-000000000001",
            "sourceId": "11111111-1111-4111-8111-111111111111",
            "title": "交报告",
            "startTime": None,
            "dueTime": {
                "rawExpression": "10月20日10:00",
                "precision": "datetime",
                "resolvedValue": "2026-10-20T10:00:00+08:00",
                "timeZone": "Asia/Shanghai",
                "status": "resolved",
            },
            "requirements": ["打印纸质版"],
            "applicability": {"text": None, "status": "not_stated"},
            "sourceExcerpt": "请于10月20日10:00前交报告",
            "reviewIssues": [],
            "reminder": {
                "mode": "none",
                "requestedAt": None,
                "scheduledAt": None,
                "relativeTo": None,
                "offsetMinutes": None,
                "state": "not_set",
                "acknowledgedAt": None,
                "revision": None,
            },
        }
    ],
}


# ------------------------------------------------------------------
# 静态结构
# ------------------------------------------------------------------

def test_import_route_and_containers_exist():
    text = (WEB / "index.html").read_text(encoding="utf-8")
    assert "#/import" in text
    for marker in ('id="view-import"', 'id="view-review"', 'id="import-form"', 'id="draft-list"'):
        assert marker in text, marker


def test_no_external_resources_after_t09():
    forbidden = re.compile(
        r"https?://|//cdn|unpkg|jsdelivr|cdnjs|googleapis|modao\.cc|tailwind|iconify"
    )
    for name in ("index.html", "styles.css", "app.js"):
        content = (WEB / name).read_text(encoding="utf-8")
        assert not forbidden.search(content), f"{name} 含外部资源引用"


def test_no_demo_data_after_t09():
    banned = ["原型演示", "参加集合", "演示数据", "示例任务"]
    for name in ("index.html", "app.js"):
        content = (WEB / name).read_text(encoding="utf-8")
        for word in banned:
            assert word not in content, f"{name} 含演示痕迹：{word}"


def test_t10_views_not_removed():
    text = (WEB / "index.html").read_text(encoding="utf-8")
    for marker in ('id="view-list"', 'id="view-detail"', 'id="task-list"', 'id="task-form"', "#/tasks"):
        assert marker in text, marker


# ------------------------------------------------------------------
# 载荷形状（node 真实执行）
# ------------------------------------------------------------------

def test_extraction_payload_is_three_keys():
    out = _ok(_run({"originalText": ORIGINAL_TEXT, "messageDate": None}))
    assert out["extractionPayload"] == {
        "source": {"kind": "text", "originalText": ORIGINAL_TEXT, "messageDate": None}
    }


def test_extraction_payload_with_message_date():
    out = _ok(_run({"originalText": ORIGINAL_TEXT, "messageDate": "2026-10-19"}))
    assert out["extractionPayload"]["source"]["messageDate"] == "2026-10-19"


def test_confirmation_source_is_full_confirmation_input():
    """确认 source 恰为契约 §4.2 SourceConfirmationInput 的八个键
    （任务单/计划口述的「九键」为笔误：列出的名字实为 8 个）。"""
    out = _ok(_run({
        "originalText": ORIGINAL_TEXT,
        "messageDate": None,
        "draftSet": DRAFT_SET,
        "drafts": DRAFT_SET["drafts"],
    }))
    payload = out["confirmationPayload"]
    assert set(payload) == {"source", "confirmedTasks"}
    assert set(payload["source"]) == {
        "id", "kind", "originalText", "messageDate",
        "importedAt", "mimeType", "fileName", "contentSha256",
    }
    # originalText 为用户粘贴原文，fileName 为 null
    assert payload["source"]["originalText"] == ORIGINAL_TEXT
    assert payload["source"]["fileName"] is None
    assert payload["source"]["id"] == DRAFT_SET["source"]["id"]
    assert payload["source"]["importedAt"] == DRAFT_SET["source"]["importedAt"]
    assert payload["source"]["contentSha256"] == DRAFT_SET["source"]["contentSha256"]


def test_confirmed_task_keys_and_draft_id_preserved():
    out = _ok(_run({
        "originalText": ORIGINAL_TEXT,
        "messageDate": None,
        "draftSet": DRAFT_SET,
        "drafts": DRAFT_SET["drafts"],
    }))
    task = out["confirmationPayload"]["confirmedTasks"][0]
    assert set(task) == {
        "draftId", "title", "startTime", "dueTime",
        "requirements", "applicability", "sourceExcerpt", "reminder",
    }
    # draftId 用后端原值
    assert task["draftId"] == "eeeeeeee-0000-4000-8000-000000000001"
    # reminder 为四键 ReminderInput（不含只读字段）
    assert set(task["reminder"]) == {"mode", "requestedAt", "relativeTo", "offsetMinutes"}
    # startTime/dueTime 为四键 TimeInfoInput（无 timeZone）
    assert "timeZone" not in task["dueTime"]
    assert set(task["dueTime"]) == {"rawExpression", "precision", "resolvedValue", "status"}


# ------------------------------------------------------------------
# O-01（sourceExcerpt）与 P10-04（时间列）
# ------------------------------------------------------------------

_BASE_FORM = {
    "title": "交报告",
    "startTime": {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
    "dueTime": {"enabled": False, "rawExpression": "", "precision": "date", "resolvedValue": "", "needsConfirmation": False},
    "requirementsText": "",
    "applicabilityStatus": "not_stated",
    "applicabilityText": "",
    "sourceExcerpt": None,
    "reminder": {"mode": "none", "requestedAt": "", "relativeTo": "", "offsetMinutes": ""},
}


def _current_with(excerpt):
    return {
        "title": "交报告", "startTime": None, "dueTime": None,
        "requirements": [], "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": excerpt,
        "reminder": {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
    }


def test_o01_null_and_null_is_omitted():
    out = _ok(_run({
        "originalText": ORIGINAL_TEXT, "messageDate": None,
        "draftSet": DRAFT_SET, "drafts": DRAFT_SET["drafts"],
        "oomFormNull": dict(_BASE_FORM),
        "oomCurrentNull": _current_with(None),
        "oomCurrentText": _current_with("请交报告"),
        "errorCode": "model_unavailable",
    }))
    assert out["sourceExcerptNullNull"] == {}, out["sourceExcerptNullNull"]


def test_o01_null_and_text_submits_null():
    out = _ok(_run({
        "originalText": ORIGINAL_TEXT, "messageDate": None,
        "draftSet": DRAFT_SET, "drafts": DRAFT_SET["drafts"],
        "oomFormNull": dict(_BASE_FORM),
        "oomCurrentNull": _current_with(None),
        "oomCurrentText": _current_with("请交报告"),
        "errorCode": "model_unavailable",
    }))
    assert out["sourceExcerptNullText"] == {"sourceExcerpt": None}


def test_error_text_table_maps_codes():
    out = _ok(_run({
        "originalText": ORIGINAL_TEXT, "messageDate": None,
        "draftSet": DRAFT_SET, "drafts": DRAFT_SET["drafts"],
        "oomFormNull": dict(_BASE_FORM),
        "oomCurrentNull": _current_with(None),
        "oomCurrentText": _current_with("请交报告"),
        "errorCode": "model_unavailable",
    }))
    assert out["errorText"], "MODEL_ERROR_TEXT 未导出或缺 model_unavailable"


@pytest.mark.parametrize("code", ["model_unavailable", "extraction_timeout", "model_output_invalid", "draft_validation_failed"])
def test_error_text_table_all_codes(code):
    out = _ok(_run({
        "originalText": ORIGINAL_TEXT, "messageDate": None,
        "draftSet": DRAFT_SET, "drafts": DRAFT_SET["drafts"],
        "oomFormNull": dict(_BASE_FORM),
        "oomCurrentNull": _current_with(None),
        "oomCurrentText": _current_with("请交报告"),
        "errorCode": code,
    }))
    assert out["errorText"], f"缺 {code} 文案"


# ------------------------------------------------------------------
# 集成：TestClient + mock 模型注入
# ------------------------------------------------------------------

def _client_with_mock(tmp_path, drafts=None, error=None):
    app = create_app(tmp_path)
    app.state.extraction_model = MockExtractionModel(drafts=drafts or [], error=error)
    return TestClient(app)


def test_extract_returns_draftset_review(tmp_path):
    client = _client_with_mock(tmp_path, drafts=[{
        "title": "交报告", "startTime": None,
        "dueTime": {"rawExpression": "10月20日", "precision": "datetime",
                    "resolvedValue": "2026-10-20T10:00:00+08:00", "status": "resolved"},
        "requirements": [], "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "原文片段",
    }])
    response = client.post("/api/v1/extractions", json={
        "source": {"kind": "text", "originalText": ORIGINAL_TEXT, "messageDate": None}
    })
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "review"
    assert len(body["drafts"]) == 1
    assert set(body["source"]) == {
        "id", "kind", "mimeType", "fileName", "messageDate", "importedAt", "contentSha256",
    }


def test_extract_no_tasks_is_not_error(tmp_path):
    client = _client_with_mock(tmp_path, drafts=[])
    response = client.post("/api/v1/extractions", json={
        "source": {"kind": "text", "originalText": ORIGINAL_TEXT, "messageDate": None}
    })
    assert response.status_code == 200
    assert response.json()["status"] == "no_tasks"


@pytest.mark.parametrize(
    "error,status,code",
    [
        (ModelUnavailableError("不可用"), 503, "model_unavailable"),
        (ModelTimeoutError("超时"), 504, "extraction_timeout"),
        (ModelOutputInvalidError("无效"), 502, "model_output_invalid"),
    ],
)
def test_extract_failure_classification(tmp_path, error, status, code):
    client = _client_with_mock(tmp_path, error=error)
    response = client.post("/api/v1/extractions", json={
        "source": {"kind": "text", "originalText": ORIGINAL_TEXT, "messageDate": None}
    })
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    # 失败绝不含 no_tasks
    assert "no_tasks" not in response.text


def test_extract_invalid_message_date_is_400(tmp_path):
    client = _client_with_mock(tmp_path, drafts=[])
    response = client.post("/api/v1/extractions", json={
        "source": {"kind": "text", "originalText": ORIGINAL_TEXT, "messageDate": "2026-2-3"}
    })
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_confirm_end_to_end_with_mock(tmp_path):
    """提取 → 确认 → 列表可见。"""
    client = _client_with_mock(tmp_path, drafts=[{
        "title": "交报告", "startTime": None,
        "dueTime": {"rawExpression": "10月20日", "precision": "datetime",
                    "resolvedValue": "2026-10-20T10:00:00+08:00", "status": "resolved"},
        "requirements": ["打印"], "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "请于10月20日前交报告",
    }])
    extraction = client.post("/api/v1/extractions", json={
        "source": {"kind": "text", "originalText": ORIGINAL_TEXT, "messageDate": None}
    }).json()
    draft = extraction["drafts"][0]
    src = extraction["source"]

    confirmed = client.post(
        f"/api/v1/draft-sets/{extraction['draftSetId']}/confirm",
        json={
            "source": {
                "id": src["id"], "kind": "text", "originalText": ORIGINAL_TEXT,
                "messageDate": src["messageDate"], "importedAt": src["importedAt"],
                "mimeType": src["mimeType"], "fileName": None,
                "contentSha256": src["contentSha256"],
            },
            "confirmedTasks": [{
                "draftId": draft["id"],
                "title": draft["title"],
                "startTime": None,
                "dueTime": {
                    "rawExpression": draft["dueTime"]["rawExpression"],
                    "precision": draft["dueTime"]["precision"],
                    "resolvedValue": draft["dueTime"]["resolvedValue"],
                    "status": draft["dueTime"]["status"],
                },
                "requirements": draft["requirements"],
                "applicability": draft["applicability"],
                "sourceExcerpt": draft["sourceExcerpt"],
                "reminder": {"mode": "none", "requestedAt": None, "relativeTo": None, "offsetMinutes": None},
            }],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert len(confirmed.json()["tasks"]) == 1

    listing = client.get("/api/v1/tasks").json()["tasks"]
    assert any(t["title"] == "交报告" for t in listing)


def test_confirm_empty_tasks_is_422(tmp_path):
    client = _client_with_mock(tmp_path, drafts=[{
        "title": "x", "startTime": None, "dueTime": None, "requirements": [],
        "applicability": {"text": None, "status": "not_stated"}, "sourceExcerpt": "x",
    }])
    extraction = client.post("/api/v1/extractions", json={
        "source": {"kind": "text", "originalText": ORIGINAL_TEXT, "messageDate": None}
    }).json()
    response = client.post(
        f"/api/v1/draft-sets/{extraction['draftSetId']}/confirm",
        json={
            "source": {
                "id": extraction["source"]["id"], "kind": "text",
                "originalText": ORIGINAL_TEXT, "messageDate": None,
                "importedAt": extraction["source"]["importedAt"],
                "mimeType": extraction["source"]["mimeType"], "fileName": None,
                "contentSha256": extraction["source"]["contentSha256"],
            },
            "confirmedTasks": [],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_confirmation"
