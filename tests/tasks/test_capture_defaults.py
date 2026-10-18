"""默认安排规则执行真实前端函数；时钟固定，不调用模型。"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parent / "web" / "app.js"
NOW = "2026-10-17T10:00:00+08:00"


def run(draft, now=NOW, refresh=None, freeze=False, reference=None):
    node = shutil.which("node")
    if not node:
        pytest.skip("本机无 node")
    script = """
const fs=require('fs');(0,eval)(fs.readFileSync(process.argv[1],'utf8'));
const input=JSON.parse(process.argv[2]);
const fn=viewHelpers.prepareCaptureDraft;
if(typeof fn!=='function'){process.stdout.write(JSON.stringify({missing:true}));process.exit(0);}
const d=fn(input.draft,new Date(input.now),input.reference);
if(input.freeze)d._automaticReminderFrozen=true;
if(input.refresh)viewHelpers.refreshAutomaticReminder(d,new Date(input.refresh));
process.stdout.write(JSON.stringify({draft:d,payload:formMapping.confirmedTasks([d])[0]}));
"""
    result = subprocess.run([node, "-e", script, str(APP_JS), json.dumps({"draft": draft, "now": now, "refresh": refresh, "freeze": freeze, "reference": reference})], capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    data = json.loads(result.stdout)
    assert not data.get("missing"), "缺少默认今天及自动提醒策略"
    return data


def task(**changes):
    return {"id": "d1", "title": "整理材料", "startTime": None, "dueTime": None,
            "requirements": [], "applicability": {"text": None, "status": "not_stated"},
            "sourceExcerpt": "整理材料", "reminder": {"mode": "none"}, **changes}


def stamp(value):
    return {"rawExpression": "原文时间", "precision": "datetime", "status": "resolved", "resolvedValue": value, "timeZone": "Asia/Shanghai"}


def test_no_time_defaults_to_today_and_one_hour_reminder():
    output = run(task())
    assert output["draft"]["startTime"]["resolvedValue"] == "2026-10-17"
    assert output["draft"]["startTime"]["rawExpression"] is None
    assert output["payload"]["reminder"]["requestedAt"] == "2026-10-17T11:00:00+08:00"
    assert output["payload"]["reminder"]["mode"] == "manual"
    assert "_automaticReminder" not in output["payload"]


def test_explicit_start_kept_and_reminded_thirty_minutes_early():
    start = stamp("2026-10-18T14:00:00+08:00")
    output = run(task(startTime=start))
    assert output["draft"]["startTime"] == start
    assert output["payload"]["reminder"] == {"mode": "relative", "requestedAt": None, "relativeTo": "start", "offsetMinutes": 30}


def test_due_time_kept_separate_from_default_start():
    due = stamp("2026-10-20T22:00:00+08:00")
    output = run(task(dueTime=due))
    assert output["draft"]["dueTime"] == due
    assert output["draft"]["startTime"]["resolvedValue"] == "2026-10-17"
    assert output["payload"]["reminder"]["relativeTo"] == "due"


def test_near_event_reminder_does_not_fall_in_past():
    output = run(task(startTime=stamp("2026-10-17T10:10:00+08:00")))
    assert output["payload"]["reminder"]["mode"] == "manual"
    assert output["payload"]["reminder"]["requestedAt"] == "2026-10-17T10:10:00+08:00"


def test_no_time_default_uses_shanghai_date_across_utc_midnight():
    output = run(task(), "2026-10-17T18:00:00Z")
    assert output["draft"]["startTime"]["resolvedValue"] == "2026-10-18"


def test_ambiguous_original_time_is_not_replaced_by_today():
    original = {"rawExpression": "下周某天", "precision": "relative", "status": "needs_confirmation", "resolvedValue": None}
    assert run(task(startTime=original))["draft"]["startTime"] == original


def test_user_reminder_is_preserved():
    reminder = {"mode": "manual", "requestedAt": "2026-10-20T15:00:00+08:00", "relativeTo": None, "offsetMinutes": None}
    assert run(task(reminder=reminder))["payload"]["reminder"] == reminder


def test_automatic_fallback_refreshes_when_confirming_later():
    output = run(task(), refresh="2026-10-17T11:20:00+08:00")
    assert output["payload"]["reminder"]["requestedAt"] == "2026-10-17T12:20:00+08:00"


def test_confirmation_retry_keeps_original_reminder_for_idempotency():
    output = run(task(), refresh="2026-10-17T11:20:00+08:00", freeze=True)
    assert output["payload"]["reminder"]["requestedAt"] == "2026-10-17T11:00:00+08:00"


@pytest.mark.parametrize("raw,reference,expected", [
    ("11月5号上午", "2026-10-17", "2026-11-05"),
    ("明天下午", "2026-10-15", "2026-10-16"),
    ("后天上午", "2026-12-31", "2027-01-02"),
])
def test_known_date_with_day_part_does_not_require_manual_clock(raw, reference, expected):
    original = {"rawExpression": raw, "precision": "day_part", "status": "needs_confirmation", "resolvedValue": None}
    result = run(task(startTime=original), reference=reference)["draft"]["startTime"]
    assert result["resolvedValue"] == expected
    assert result["precision"] == "date"
    assert result["status"] == "resolved"
    assert result["rawExpression"] == raw


@pytest.mark.parametrize("raw", ["下周某天", "明天下午，具体日期暂定", "2月30号上午", "每日20:30", "11月5号-7号上午", "11月5号和11月6号上午"])
def test_truly_uncertain_or_invalid_time_stays_pending(raw):
    original = {"rawExpression": raw, "precision": "day_part", "status": "needs_confirmation", "resolvedValue": None}
    assert run(task(startTime=original))["draft"]["startTime"] == original
