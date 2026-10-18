"""T13 Part A：截图导入界面测试。

三层：
1. 静态结构（index.html 容器与 accept；零外部资源沿用 test_frontend_import 的扫描）
2. node 桥（app.js 纯函数区 + DOM 桩）：图片确认载荷（四键时间、originalText=null）、
   multipart 字段构造、文字/截图互斥、错误文案映射、no_tasks 信息样式
3. TestClient + mock 视觉模型：图片提取 → 核对 → 确认（重传原图）→ 列表 → 原图回看

零真实调用：mock 注入 + conftest 默认阻断外呼。
"""

from __future__ import annotations

import json
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
from app.modules.tasks.services.source_files import MAX_IMAGE_BYTES

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
APP_JS = WEB / "app.js"
INDEX_HTML = WEB / "index.html"


def make_png() -> bytes:
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )


PNG = make_png()

DRAFT = {
    "title": "提交社会实践材料",
    "startTime": None,
    "dueTime": {
        "rawExpression": "10月19日中午12:00前",
        "precision": "datetime",
        "resolvedValue": "2026-10-19T12:00:00+08:00",
        "timeZone": "Asia/Shanghai",   # 服务端返回值：确认时不得回传（T13 坑①）
        "status": "resolved",
    },
    "requirements": ["服务单位盖章"],
    "applicability": {"text": None, "status": "not_stated"},
    "sourceExcerpt": "10月19日中午12:00前",
}

DRAFT_SET_SAMPLE = {
    "draftSetId": "dddddddd-0000-4000-8000-000000000001",
    "source": {
        "id": "11111111-1111-4111-8111-111111111111",
        "kind": "image",
        "mimeType": "image/png",
        "fileName": "shot.png",
        "messageDate": "2026-10-17",
        "importedAt": "2026-10-17T08:00:00+08:00",
        "contentSha256": "a" * 64,
    },
    "status": "review",
    "drafts": [
        {
            "id": "eeeeeeee-0000-4000-8000-000000000001",
            "sourceId": "11111111-1111-4111-8111-111111111111",
            "title": "提交社会实践材料",
            "startTime": None,
            "dueTime": {
                "rawExpression": "10月19日中午12:00前",
                "precision": "datetime",
                "resolvedValue": "2026-10-19T12:00:00+08:00",
                "timeZone": "Asia/Shanghai",
                "status": "resolved",
            },
            "requirements": ["服务单位盖章"],
            "applicability": {"text": None, "status": "not_stated"},
            "sourceExcerpt": "10月19日中午12:00前",
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


# ---------------------------------------------------------------------------
# node 桥
# ---------------------------------------------------------------------------

DOM_STUB = r"""
globalThis.__registry = {};
function makeNode(tag) {
  const n = {
    tagName: tag, children: [], className: '', href: '', textContent: '', hidden: false,
    innerHTML: '', disabled: false, value: '', src: '', alt: '', _listeners: {},
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
['import-text','import-file','import-preview','import-mode','import-notice',
 'view-import','view-review','draft-list','error-panel','btn-extract','btn-clear-file',
 'btn-confirm-drafts','review-meta'].forEach(id => register(id));
globalThis.document = {
  createElement: makeNode,
  getElementById: (id) => globalThis.__registry[id] || null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  hidden: false,
};
globalThis.window = { addEventListener: () => {}, confirm: () => true };
globalThis.URL = {
  createObjectURL: (f) => 'blob:local/' + (f && f.name ? f.name : 'x'),
  revokeObjectURL: () => {},
};
globalThis.sessionStorage = (() => {
  const m = new Map();
  return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v) };
})();
"""

NODE_RUNNER = r"""
const fs = require('fs');
const stub = fs.readFileSync(process.argv[2], 'utf8');
(0, eval)(stub);
const src = fs.readFileSync(process.argv[3], 'utf8');
const input = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
const out = {};
(async () => {
  try {
    (0, eval)(src);
    const fm = globalThis.formMapping;
    const iv = globalThis.importView;
    const reg = globalThis.__registry;

    if (input.draftSet) {
      out.imageConfirmation = fm.buildImageConfirmationPayload(input.draftSet, input.drafts);
      out.textConfirmation = fm.buildConfirmationPayload(input.draftSet, '原文', input.drafts);
    }
    const file = { name: 'shot.png', size: 2048, type: 'image/png' };
    out.fieldsWithDate = fm.buildImageExtractionFields(file, '2026-10-19')
      .map(p => [p[0], typeof p[1] === 'object' && p[1] !== null ? p[1].name : p[1]]);
    out.fieldsNoDate = fm.buildImageExtractionFields(file, null)
      .map(p => [p[0], typeof p[1] === 'object' && p[1] !== null ? p[1].name : p[1]]);
    out.modeWithFile = fm.importMode(true);
    out.modeWithoutFile = fm.importMode(false);

    out.errorTexts = ['source_too_large', 'unsupported_media_type', 'source_unreadable',
      'source_content_missing', 'source_content_mismatch', 'empty_confirmation',
      'model_unavailable', 'extraction_timeout', 'model_output_invalid',
      'draft_validation_failed', 'network_error']
      .map(c => [c, globalThis.MODEL_ERROR_TEXT[c] || null]);
    out.errorMapping = iv.errorFor({ status: 415, code: 'unsupported_media_type', message: 'raw' });

    out.modeAfterSelect = iv.selectFile(file);
    out.textareaDisabled = reg['import-text'].disabled;
    out.textareaValue = reg['import-text'].value;
    out.previewHidden = reg['import-preview'].hidden;
    out.previewChildren = reg['import-preview'].children.length;
    out.previewImgSrc = reg['import-preview'].children[0] ? reg['import-preview'].children[0].src : null;
    out.previewMeta = reg['import-preview'].children[1] ? reg['import-preview'].children[1].textContent : null;
    out.hintHidden = reg['import-mode'].hidden;
    out.hintText = reg['import-mode'].textContent;
    out.hintClass = reg['import-mode'].className;

    iv.showNoTasksNotice();
    out.noticeHidden = reg['import-notice'].hidden;
    out.noticeClass = reg['import-notice'].className;
    out.noticeText = reg['import-notice'].textContent;

    out.modeAfterTextEdit = iv.onTextEdited();
    out.previewHiddenAfterText = reg['import-preview'].hidden;
    out.fileClearedAfterText = iv.mode() === 'text';

    out.modeAfterClear = iv.clearFile();
    out.textareaEnabledAfterClear = !reg['import-text'].disabled;
    out.previewHiddenAfterClear = reg['import-preview'].hidden;
  } catch (e) {
    out.__error = String(e && e.stack || e);
  }
  fs.writeFileSync(process.argv[5], JSON.stringify(out), 'utf8');
})();
"""


def _run_node(input_data: dict) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("本机无 node，无法真实执行 app.js 视图区")
    with tempfile.TemporaryDirectory() as td:
        stub = Path(td) / "dom.js"
        runner = Path(td) / "runner.js"
        inp = Path(td) / "input.json"
        outp = Path(td) / "output.json"
        stub.write_text(DOM_STUB, encoding="utf-8")
        runner.write_text(NODE_RUNNER, encoding="utf-8")
        inp.write_text(json.dumps(input_data, ensure_ascii=False), encoding="utf-8")
        res = subprocess.run(
            [node, str(runner), str(stub), str(APP_JS), str(inp), str(outp)],
            capture_output=True, timeout=60,
        )
        assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
        out = json.loads(outp.read_text(encoding="utf-8"))
    assert "__error" not in out, out.get("__error")
    return out


# ---------------------------------------------------------------------------
# 1. 静态结构
# ---------------------------------------------------------------------------


def test_import_view_has_image_controls():
    html = INDEX_HTML.read_text(encoding="utf-8")
    for marker in (
        'id="import-file"', 'accept="image/png,image/jpeg"',
        'id="import-preview"', 'id="import-mode"', 'id="btn-clear-file"',
        'id="view-import"', 'id="draft-list"',
    ):
        assert marker in html, marker


def test_image_import_has_no_external_resource():
    import re

    forbidden = re.compile(
        r"https?://|//cdn|unpkg|jsdelivr|cdnjs|googleapis|tailwind|iconify"
    )
    for name in ("index.html", "styles.css", "app.js"):
        content = (WEB / name).read_text(encoding="utf-8")
        assert not forbidden.search(content), f"{name} 含外部资源引用"


def test_app_js_never_hand_writes_multipart_content_type():
    """multipart 的 boundary 必须交给浏览器/运行时生成（手写会 400）。"""
    source = APP_JS.read_text(encoding="utf-8")
    assert "multipart/form-data" not in source


# ---------------------------------------------------------------------------
# 2. 纯函数区（node 真实执行）
# ---------------------------------------------------------------------------


def test_image_confirmation_source_shape_and_null_original_text():
    out = _run_node({"draftSet": DRAFT_SET_SAMPLE, "drafts": DRAFT_SET_SAMPLE["drafts"]})

    payload = out["imageConfirmation"]
    assert set(payload) == {"source", "confirmedTasks"}
    assert set(payload["source"]) == {
        "id", "kind", "originalText", "messageDate",
        "importedAt", "mimeType", "fileName", "contentSha256",
    }
    assert payload["source"]["kind"] == "image"
    assert payload["source"]["originalText"] is None
    assert payload["source"]["fileName"] == "shot.png"
    assert payload["source"]["contentSha256"] == "a" * 64


def test_image_confirmation_times_are_four_keys_without_time_zone():
    """T13 坑①：确认时时间对象只回传四键；回传 timeZone 会 400。"""
    out = _run_node({"draftSet": DRAFT_SET_SAMPLE, "drafts": DRAFT_SET_SAMPLE["drafts"]})

    task = out["imageConfirmation"]["confirmedTasks"][0]
    assert set(task) == {
        "draftId", "title", "startTime", "dueTime",
        "requirements", "applicability", "sourceExcerpt", "reminder",
    }
    assert set(task["dueTime"]) == {"rawExpression", "precision", "resolvedValue", "status"}
    assert "timeZone" not in task["dueTime"]
    assert set(task["reminder"]) == {"mode", "requestedAt", "relativeTo", "offsetMinutes"}


def test_text_confirmation_payload_unchanged():
    out = _run_node({"draftSet": DRAFT_SET_SAMPLE, "drafts": DRAFT_SET_SAMPLE["drafts"]})
    # 文字路径仍把用户原文放进 source.originalText（行为零回退）
    assert out["textConfirmation"]["source"]["originalText"] == "原文"


def test_image_extraction_fields_include_file_and_optional_date():
    out = _run_node({})
    assert out["fieldsWithDate"] == [["file", "shot.png"], ["messageDate", "2026-10-19"]]
    # 未填日期时省略该部件（后端把空串判 400）
    assert out["fieldsNoDate"] == [["file", "shot.png"]]


def test_import_mode_is_exclusive():
    out = _run_node({})
    assert out["modeWithFile"] == "image"
    assert out["modeWithoutFile"] == "text"


def test_error_text_covers_upload_and_model_codes():
    out = _run_node({})
    missing = [code for code, text in out["errorTexts"] if not text]
    assert missing == [], f"缺文案：{missing}"
    assert out["errorMapping"]["code"] == "unsupported_media_type"
    assert "PNG" in out["errorMapping"]["message"]


# ---------------------------------------------------------------------------
# 3. DOM 桩：选图预览 / 互斥 / no_tasks 提示
# ---------------------------------------------------------------------------


def test_select_file_previews_locally_and_disables_text():
    out = _run_node({})
    assert out["modeAfterSelect"] == "image"
    assert out["textareaDisabled"] is True
    assert out["textareaValue"] == ""
    assert out["previewHidden"] is False
    assert out["previewChildren"] == 2
    # 本地 blob URL，绝不指向外部地址
    assert out["previewImgSrc"].startswith("blob:local/")
    assert "shot.png" in out["previewMeta"]
    assert out["hintHidden"] is False
    assert "截图模式" in out["hintText"]
    assert "notice-info" in out["hintClass"]


def test_no_tasks_uses_info_notice():
    out = _run_node({})
    assert out["noticeHidden"] is False
    assert "notice-info" in out["noticeClass"]
    assert "未发现待办事项" in out["noticeText"]


def test_text_edit_clears_selected_file():
    out = _run_node({})
    assert out["modeAfterTextEdit"] == "text"
    assert out["previewHiddenAfterText"] is True
    assert out["fileClearedAfterText"] is True


def test_clear_file_restores_text_mode():
    out = _run_node({})
    assert out["modeAfterClear"] == "text"
    assert out["textareaEnabledAfterClear"] is True
    assert out["previewHiddenAfterClear"] is True


# ---------------------------------------------------------------------------
# 4. 集成：提取 → 核对 → 确认（重传原图）→ 列表 → 原图回看
# ---------------------------------------------------------------------------


def _client(tmp_path, **mock_kwargs) -> TestClient:
    app = create_app(tmp_path)
    app.state.extraction_model = MockExtractionModel(**mock_kwargs)
    return TestClient(app)


def _png_file(name: str = "shot.png", data: bytes = PNG):
    import io

    return ("file", (name, io.BytesIO(data), "image/png"))


def _extract(client: TestClient, data: dict | None = None):
    return client.post("/api/v1/extractions", files=[_png_file()], data=data or {})


def test_image_extract_then_confirm_uses_frontend_payload(tmp_path):
    client = _client(tmp_path, image_drafts=[DRAFT])

    extracted = _extract(client, {"messageDate": "2026-10-17"})
    assert extracted.status_code == 200, extracted.text
    draft_set = extracted.json()
    assert draft_set["source"]["kind"] == "image"
    assert draft_set["drafts"][0]["title"] == DRAFT["title"]

    # 前端载荷由 node 真实生成（与浏览器同一份代码）
    payload = _run_node({"draftSet": draft_set, "drafts": draft_set["drafts"]})["imageConfirmation"]

    confirmed = client.post(
        f"/api/v1/draft-sets/{draft_set['draftSetId']}/confirm",
        files=[_png_file()],
        data={"confirmation": json.dumps(payload, ensure_ascii=False)},
    )
    assert confirmed.status_code == 200, confirmed.text
    tasks = confirmed.json()["tasks"]
    assert len(tasks) == 1 and tasks[0]["title"] == DRAFT["title"]

    listed = client.get("/api/v1/tasks").json()["tasks"]
    assert any(t["title"] == DRAFT["title"] for t in listed)

    media = client.get(f"/api/v1/sources/{draft_set['source']['id']}/content")
    assert media.status_code == 200
    assert media.headers["Content-Type"].startswith("image/png")
    assert media.content == PNG


def test_image_confirm_without_file_part_is_400(tmp_path):
    """前端必须重传原图（T13 坑②）：漏发 file 时后端明确拒绝，不静默成功。"""
    client = _client(tmp_path, image_drafts=[DRAFT])
    draft_set = _extract(client).json()
    payload = _run_node({"draftSet": draft_set, "drafts": draft_set["drafts"]})["imageConfirmation"]

    response = client.post(
        f"/api/v1/draft-sets/{draft_set['draftSetId']}/confirm",
        data={"confirmation": json.dumps(payload, ensure_ascii=False)},
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_request"


def test_image_confirm_byte_mismatch_is_409(tmp_path):
    client = _client(tmp_path, image_drafts=[DRAFT])
    draft_set = _extract(client).json()
    payload = _run_node({"draftSet": draft_set, "drafts": draft_set["drafts"]})["imageConfirmation"]
    payload["source"]["contentSha256"] = "b" * 64

    response = client.post(
        f"/api/v1/draft-sets/{draft_set['draftSetId']}/confirm",
        files=[_png_file()],
        data={"confirmation": json.dumps(payload, ensure_ascii=False)},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "source_content_mismatch"


def test_image_extract_no_tasks_is_not_error(tmp_path):
    client = _client(tmp_path, image_drafts=[])

    response = _extract(client)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "no_tasks"
    assert body["drafts"] == []


@pytest.mark.parametrize(
    "error,status,code",
    [
        (ModelUnavailableError("x"), 503, "model_unavailable"),
        (ModelTimeoutError("x"), 504, "extraction_timeout"),
        (ModelOutputInvalidError("x"), 502, "model_output_invalid"),
    ],
)
def test_image_extract_failure_classification(tmp_path, error, status, code):
    client = _client(tmp_path, error=error)

    response = _extract(client)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "no_tasks" not in response.text


def test_image_extract_invalid_draft_is_502(tmp_path):
    client = _client(tmp_path, image_drafts=[{**DRAFT, "title": "   "}])

    response = _extract(client)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "draft_validation_failed"


def test_image_extract_oversize_is_413(tmp_path):
    client = _client(tmp_path, image_drafts=[DRAFT])
    # 先确认小样本通路正常，再验证超限分支
    assert _extract(client).status_code == 200

    big = PNG + b"\x00" * (MAX_IMAGE_BYTES + 1)
    response = client.post("/api/v1/extractions", files=[_png_file(data=big)])
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "source_too_large"


def test_image_extract_rejects_non_image_is_415(tmp_path):
    import io

    client = _client(tmp_path, image_drafts=[DRAFT])
    response = client.post(
        "/api/v1/extractions",
        files=[("file", ("fake.png", io.BytesIO(b"not an image"), "image/png"))],
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_image_extract_truncated_is_422(tmp_path):
    client = _client(tmp_path, image_drafts=[DRAFT])
    response = client.post(
        "/api/v1/extractions", files=[_png_file(data=PNG[: len(PNG) // 2])]
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "source_unreadable"


def test_text_path_still_works_when_no_file(tmp_path):
    """互斥的另一半：无文件时仍走文字 JSON 路径（零回退）。"""
    client = _client(tmp_path, drafts=[{
        "title": "交报告", "startTime": None, "dueTime": None, "requirements": [],
        "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "请交报告",
    }])

    response = client.post("/api/v1/extractions", json={
        "source": {"kind": "text", "originalText": "请交报告", "messageDate": None}})

    assert response.status_code == 200
    assert response.json()["status"] == "review"
    assert response.json()["source"]["kind"] == "text"
