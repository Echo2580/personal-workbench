"""手动新建待办对话框 → POST /api/v1/tasks 载荷的回归。

历史缺陷（2026-10-18 实测）：只填「截止日期」、不填「截止时间」时，前端把
``precision`` 写成 ``date``，``resolvedValue`` 却是补了默认 09:00 的 datetime
（``2026-10-18T09:00:00+08:00``）。后端 §4.2 TimeInfo 校验要求 date 精度的值
严格为 ``YYYY-MM-DD``，于是返回 422 ``task_validation_failed``。

这里用本机 node 真实导入生产前端的纯函数生成载荷：既断言对话框产出的形状，
也把同一份载荷交给真实接口确认 201——前端形状与后端契约一起回归。
覆盖三种提醒：不提醒 / 提前 N 分钟（相对截止时间）/ 指定提醒时间（绝对时刻）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.modules.tasks.app_factory import create_tasks_app

APP_JS = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "web"
    / "modules"
    / "tasks"
    / "app.js"
)

_RUNNER = """
import {readFileSync} from 'node:fs';
const [srcPath, inputPath] = process.argv.slice(2);
const src = readFileSync(srcPath, 'utf8');
// 生产文件按 <script type="module"> 加载；node 里用 data: URL 当 ESM 执行。
const mod = await import(
  'data:text/javascript;base64,' + Buffer.from(src, 'utf8').toString('base64')
);
const cases = JSON.parse(readFileSync(inputPath, 'utf8'));
process.stdout.write(JSON.stringify(cases.map((c) => mod.buildManualTaskPayload(c))));
"""


def _build_payloads(tmp_path: Path, cases: list[dict]) -> list[dict]:
    """真实执行生产前端纯函数，返回对话框对每个输入的请求体。"""
    node = shutil.which("node")
    if node is None:
        pytest.skip("本机无 node，无法真实执行待办模块纯函数")
    runner = tmp_path / "manual-payload-runner.mjs"
    inputs = tmp_path / "manual-payload-inputs.json"
    runner.write_text(_RUNNER, encoding="utf-8")
    inputs.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [node, str(runner), str(APP_JS), str(inputs)],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return json.loads(result.stdout.decode("utf-8"))


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_tasks_app(tmp_path / "data"))


def test_default_reminder_none_and_date_only_due_time(tmp_path):
    (payload,) = _build_payloads(
        tmp_path,
        [
            {
                "title": " 今天吃大盘鸡 ",
                "date": "2099-10-19",
                "time": "",
                "requirements": "  只收 PDF  \n\n提交到学习平台\n",
                "reminderMode": "none",
            }
        ],
    )

    # 只填日期：date 精度的值必须是 YYYY-MM-DD，不能偷偷补 09:00。
    assert payload["title"] == "今天吃大盘鸡"
    assert payload["requirements"] == ["只收 PDF", "提交到学习平台"]
    assert payload["dueTime"] == {
        "rawExpression": "2099-10-19",
        "precision": "date",
        "resolvedValue": "2099-10-19",
        "status": "resolved",
    }
    assert payload["reminder"] == {
        "mode": "none",
        "requestedAt": None,
        "relativeTo": None,
        "offsetMinutes": None,
    }

    response = _client(tmp_path).post("/api/v1/tasks", json=payload)
    assert response.status_code == 201, response.text
    task = response.json()["task"]
    assert task["dueTime"]["precision"] == "date"
    assert task["dueTime"]["resolvedValue"] == "2099-10-19"
    assert task["reminder"]["mode"] == "none"
    assert task["reminder"]["state"] == "not_set"
    assert task["reviewIssues"] == []


def test_relative_reminder_uses_custom_offset_minutes(tmp_path):
    (payload,) = _build_payloads(
        tmp_path,
        [
            {
                "title": "交实验报告",
                "date": "2099-10-19",
                "time": "18:00",
                "requirements": "",
                "reminderMode": "relative",
                "reminderOffset": "10",
            }
        ],
    )

    assert payload["dueTime"] == {
        "rawExpression": "2099-10-19 18:00",
        "precision": "datetime",
        "resolvedValue": "2099-10-19T18:00:00+08:00",
        "status": "resolved",
    }
    assert payload["reminder"] == {
        "mode": "relative",
        "requestedAt": None,
        "relativeTo": "due",
        "offsetMinutes": 10,
    }

    response = _client(tmp_path).post("/api/v1/tasks", json=payload)
    assert response.status_code == 201, response.text
    reminder = response.json()["task"]["reminder"]
    assert reminder["state"] == "scheduled"
    assert reminder["offsetMinutes"] == 10
    assert reminder["scheduledAt"].startswith("2099-10-19T17:50")


def test_manual_reminder_time_works_without_deadline(tmp_path):
    (payload,) = _build_payloads(
        tmp_path,
        [
            {
                "title": "指定提醒时间",
                "date": "",
                "time": "",
                "requirements": "",
                "reminderMode": "manual",
                "reminderAt": "2099-10-19T09:30",
            }
        ],
    )

    # 绝对提醒时刻按 Asia/Shanghai 转成契约时间戳；没有截止日期也可以提醒。
    assert "dueTime" not in payload
    assert payload["reminder"] == {
        "mode": "manual",
        "requestedAt": "2099-10-19T09:30:00+08:00",
        "relativeTo": None,
        "offsetMinutes": None,
    }

    response = _client(tmp_path).post("/api/v1/tasks", json=payload)
    assert response.status_code == 201, response.text
    task = response.json()["task"]
    assert task["dueTime"] is None
    assert task["reminder"]["mode"] == "manual"
    assert task["reminder"]["state"] == "scheduled"
    assert task["reminder"]["scheduledAt"].startswith("2099-10-19T09:30")
