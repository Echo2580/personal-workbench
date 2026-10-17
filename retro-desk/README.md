# Retro Desk · 轻复古个人工作台首页

视觉风格：Poolsuite / Mac System 7 —— 粉色抖动桌面、条纹标题栏窗口（方角黑描边）、衬线日历数字、顶部菜单栏（实时日期）、底部图标坞。
独立的首页交互演示：复古显像管电视 + 像素鲸鱼宠物 + 桌面小件（便笺 / 撕页日历 / 今日待办 / 项目文件夹）。
纯 HTML + CSS + JavaScript，零依赖、零外部素材，断网可跑。

## 启动方式

方式一（最简单）：直接双击 `index.html` 用浏览器打开。

方式二（本地服务，推荐）：在本目录执行

```powershell
# 在当前目录起一个静态服务器；只影响本机，浏览器访问 http://localhost:8765
python -m http.server 8765
```

然后浏览器访问 `http://localhost:8765`。

## 目录结构

```
retro-desk/
├── index.html        # 页面结构 + 脚本加载顺序
├── css/style.css     # 全部视觉（墙面/桌面/电视/纸张/像素渲染）
└── js/
    ├── state.js      # RD.Bus 事件总线 + RD.Store（localStorage 持久化）
    ├── tv.js         # 电视：电源/频道动画/雪花/暂停/本地视频/音量
    ├── whale.js      # 像素鲸鱼：状态机 + 手绘像素渲染 + 点击拖动
    ├── chat.js       # 聊天窗口 + RD.chatAdapter（演示回复）
    ├── widgets.js    # 日历 / 待办 / 便笺 / 项目文件夹
    ├── drag.js       # 拖动 / 置顶 / 收起恢复 / 整理桌面
    └── main.js       # 启动入口
```

## 素材说明

- 所有物件（电视、日历、纸张、文件夹、鲸鱼）均为 CSS / Canvas 手绘，无图片素材。
- 三个电视频道（像素日落海面、雨夜、星空）为 Canvas 实时动画，打开页面即播放。
- 天气为演示数据，已在日历上明确标注。
- 聊天为本地演示回复，不需要 API 密钥。

## 后续接入位置

| 要接什么 | 改哪里 |
|---|---|
| DeepSeek 对话 | `js/chat.js` 的 `RD.chatAdapter`（密钥放后端，前端只调自己的接口） |
| 项目入口 | `js/widgets.js` 顶部的 `PROJECTS` 数组 |
| 真实天气 | `js/widgets.js` 的 `renderCalendar()` 中标注行 |
| 新频道 | `js/tv.js` 的 `drawers` 数组 |
| 新联动 | 发布方 `RD.Bus.emit()`，订阅方 `RD.Bus.on()`（见 `state.js` 注释） |

## 持久化

`localStorage` 键 `retroDesk.v1`，保存：桌面布局、待办、便笺、频道、电源、静音/音量、鲸鱼暂停状态。
临时视频地址（ObjectURL）不保存，刷新后需重新选择文件。
