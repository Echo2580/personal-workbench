---
name: Personal Workbench
description: 深墨绿与浅黄绿的本机个人工作台，依据用户 2026-10-18 选定的第一张参考图。
colors:
  background: "#151a1c"
  sidebar: "#171c1f"
  surface: "#1e2528"
  raised: "#252e32"
  border: "#344045"
  text: "#edf1ef"
  muted: "#a8b3b5"
  primary: "#c8e88b"
  on-primary: "#202b19"
  danger: "#f0a799"
  warning: "#e9cd8e"
  info: "#96c6e9"
typography:
  body:
    fontFamily: "Segoe UI, Microsoft YaHei UI, sans-serif"
    fontSize: "14px"
    lineHeight: 1.6
  heading:
    fontFamily: "Segoe UI, Microsoft YaHei UI, sans-serif"
    fontSize: "26px"
    fontWeight: 650
rounded:
  control: "6px"
  panel: "8px"
spacing:
  compact: "8px"
  normal: "16px"
  section: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.control}"
    padding: "7px 14px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
---

# 工作台视觉规范

2026-10-18 用户选择的第一张参考图为全站视觉依据，替代旧暖白配色。Operate 模式，Windows 本机、离线资源、原生 JS/CSS。

## Colors
- 背景 #151a1c，侧栏 #171c1f，面板 #1e2528，抬升表面 #252e32，边界 #344045。
- 正文 #edf1ef，辅助文字 #a8b3b5，主色 #c8e88b，主按钮文字 #202b19。
- 成功 #bedf8a / #29372b；错误 #f0a799 / #392b2b；提醒 #e9cd8e / #383328；信息 #96c6e9 / #25333f。
- Segoe UI / Microsoft YaHei UI；路径和命令使用 Consolas。正文 13–14px，辅助至少 11px，模块标题 16–18px，页面标题 26px；首页标语 34px。

## Layout
- 桌面侧栏 184px，顶栏 64px；1024px 以下使用可展开导航。全站搜索位于顶栏左侧，日期和头像位于右侧。
- 首页左列为我的一天、今日待办，右列为天气、世界快讯；底部为常用入口、接下来、随手记。760px 以下按顺序单列。
- 首页保留真实待办、完成进度、筛选、快捷记录、项目、自定义入口、天气、新闻、日程和笔记。没有演示数据写入产品。
- 面板圆角 7–8px，按钮/输入圆角 6px；细边界，无大面积装饰渐变。主动作浅黄绿，其余控件使用深色表面。
- 所有控件有 hover、焦点、禁用、错误状态。任务状态用文字和颜色共同表达。弹窗、抽屉、原图回看、提醒均遵循深色系统。
- 项目启动、停止、改名、移除、恢复，截图导入与核对，手动待办，长期计划与习惯，设置和备份流程保持原契约。

## Components
styles/tokens.css 管基础 tokens 和控件；shell.css / projects/styles.css / tasks/styles.css 管各自结构。
styles/theme.css 在本地 tailwind.css 后加载，前段把旧静态工具类颜色映射为语义变量，后段管理本次全站外观和首页布局。动态载入的待办 CSS 自带同一套深色 tokens，不依赖载入顺序。

## Do's and Don'ts
开发仅在 wb 和独立数据实例完成，截图与验证记录位于相邻 gpt/.planning/2026-10-18-dark-workbench/。按 docs/release.md，仅在用户明确要求发布时迁移 wb-stable。
