"""首页「今日待办」卡片接真实模块数据的回归。

链路：给运行中的应用注入 Mock 模型 → 走 提取 + 确认 接口建一条「今天到期」的真实待办 →
回到首页断言卡片显示真实标题/时间/要求条数，勾选后进度与徽标同步。

首页口径（用户已定）：今天到期 + 逾期未完成；无日期任务不上首页。
"""

from datetime import datetime, timedelta, timezone

from playwright.sync_api import expect

from app.modules.tasks.services.model_adapter import MockExtractionModel

SHANGHAI = timezone(timedelta(hours=8))
TODAY_DUE = datetime.now(SHANGHAI).replace(hour=18, minute=0, second=0, microsecond=0)

DRAFTS = [
    {
        "title": "提交实验报告",
        "startTime": None,
        "dueTime": {
            "rawExpression": "今天 18:00",
            "precision": "datetime",
            "resolvedValue": TODAY_DUE.isoformat(),
            "status": "resolved",
        },
        "requirements": ["学习平台提交", "只收 PDF"],
        "applicability": {"text": None, "status": "not_stated"},
        "sourceExcerpt": "今天18:00前提交实验报告，只收PDF。",
    }
]

SEED_TEXT = "今天18:00前在学习平台提交实验报告，只收PDF。"


def _strip_timezone(info):
    if not info:
        return info
    return {k: v for k, v in info.items() if k != "timeZone"}


def _seed_task(page):
    """在页面内用同源 fetch 建一条真实待办（自动带 Origin/Host）。"""
    script = """
    async ({text, dueValue}) => {
      const boot = await (await fetch('/api/v1/bootstrap')).json();
      const headers = {'Content-Type': 'application/json', 'X-Workbench-Token': boot.token};
      const ex = await fetch('/api/v1/extractions', {
        method: 'POST', headers,
        body: JSON.stringify({source: {kind: 'text', originalText: text}}),
      });
      if (!ex.ok) return {step: 'extract', status: ex.status, body: await ex.text()};
      const batch = await ex.json();
      const draft = batch.drafts[0];
      draft.dueTime.resolvedValue = dueValue;
      const strip = (i) => i == null ? i
        : Object.fromEntries(Object.entries(i).filter(([k]) => k !== 'timeZone'));
      const confirmation = {
        source: {...batch.source, originalText: text},
        confirmedTasks: [{
          draftId: draft.id,
          title: draft.title,
          startTime: strip(draft.startTime),
          dueTime: strip(draft.dueTime),
          requirements: draft.requirements,
          applicability: draft.applicability,
          sourceExcerpt: draft.sourceExcerpt,
          reminder: {mode: 'none', requestedAt: null, relativeTo: null, offsetMinutes: null},
        }],
      };
      const cf = await fetch('/api/v1/draft-sets/' + batch.draftSetId + '/confirm', {
        method: 'POST', headers, body: JSON.stringify(confirmation),
      });
      if (!cf.ok) return {step: 'confirm', status: cf.status, body: await cf.text()};
      return {ok: true};
    }
    """
    result = page.evaluate(script, {"text": SEED_TEXT, "dueValue": TODAY_DUE.isoformat()})
    assert result.get("ok"), result


def test_home_shows_today_task_from_module(ui):
    page, app, _root = ui
    app.state.extraction_model = MockExtractionModel(drafts=DRAFTS)
    _seed_task(page)

    page.goto(page.url.split("#")[0])
    page.wait_for_load_state("networkidle")

    card = page.locator("#todoCard")
    expect(card.get_by_text("提交实验报告")).to_be_visible()
    expect(card.get_by_text("2 条要求")).to_be_visible()
    expect(card.get_by_text("今日已完成 0 / 1")).to_be_visible()

    # 勾选完成 → 进度 1/1、标题变为已完成
    card.get_by_role("button", name="标记为完成：提交实验报告").click()
    expect(card.get_by_text("今日已完成 1 / 1")).to_be_visible()
    expect(card.get_by_role("button", name="标记为未完成：提交实验报告")).to_be_visible()
