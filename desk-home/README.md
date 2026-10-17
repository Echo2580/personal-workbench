# 个人工作台 · 桌面首页原型

Poolsuite 式复古桌面氛围 + 纸面窗口的个人工作台首页。React + TypeScript + Vite + Tailwind，
零外部素材（壁纸、像素鲸鱼全部手绘），断网可跑。

## 运行

```powershell
# 1. 安装依赖（已完成的可跳过；Node 20+）
npm install

# 2. 启动开发服务；只影响本机，浏览器访问 http://localhost:3000
npm run dev
```

生产构建：`npm run build`，产物在 `dist/`，任意静态服务器可托管。

## ⚠️ 关于 scripts/dev.mjs（勿删）

本机安全软件会拦截**中文路径下**的 `esbuild.exe` 读取文件
（症状：`winapi error #5`，ACCESS_DENIED，`--version` 正常但读任何文件都失败）。
`scripts/dev.mjs` 在每次启动时把 esbuild 复制为英文路径下的改名副本
（`%LOCALAPPDATA%\PersonalWorkbench\esbuild\esbuild-win.exe`），
通过官方环境变量 `ESBUILD_BINARY_PATH` 让 vite/esbuild 全链路改走副本。
`npm run dev` / `npm run build` / `npm run preview` 均已包一层，无需手动处理；
副本不存在才复制，npm 重装依赖后自愈。

## 演示 / 检查参数

| 参数 | 效果 |
|---|---|
| `?demo=fresh` | 完全首次状态（默认布局 + 默认内容），忽略本机存档 |
| `?demo=multi` | 三窗阶梯叠放预设（日历底 / 项目中 / 天气顶） |
| `?wall=night` | 指定壁纸：sunset / mist / night / ridge / oat / slate / charcoal / midnight |

日常使用不带参数，自动恢复上次的窗口布局与内容。

## 交互回归

```powershell
# 终端 1：dev server
npm run dev

# 终端 2：起一台带 CDP 的 Chrome
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --remote-debugging-port=9222 --user-data-dir="$env:TEMP\cdp-profile" about:blank

# 终端 3：跑 27 项断言（拖动/钳制/吸附/置顶/dock 规则/缩放/最大化/收回保留/刷新恢复/壁纸/恢复默认）
node scripts/interaction-check.mjs
```

## 目录结构

```
src/
├── desktop/
│   ├── useDesk.ts          # 状态中枢：窗口布局/层级/显隐/用户输入/壁纸 + localStorage 持久化
│   ├── WindowFrame.tsx     # 单窗口：标题栏拖动（DOM 直写保跟手）/边缘缩放/双击最大化/边界钳制
│   ├── Dock.tsx            # 底部应用栏（项目/待办/便笺/日历 + 分隔的外观设置）
│   ├── CornerInfo.tsx      # 左上角日期 + 天气（演示数据）
│   ├── Whale.tsx           # 右下角像素鲸鱼（box-shadow 手绘，不承担任何功能）
│   ├── wallpapers.tsx      # 8 张手绘壁纸（CSS 渐变 + SVG），缩略图与全尺寸共用组件
│   ├── Desktop.tsx         # 桌面组装
│   └── apps/               # TodoApp / NoteApp / CalendarApp / ProjectApp / WeatherApp / SettingsApp
├── index.css               # 纸面复古设计系统（变量、窗口、dock、各应用元件）
└── pages/Home.tsx          # 入口
scripts/
├── dev.mjs                 # esbuild 环境适配启动包装（见上文⚠️）
└── interaction-check.mjs   # CDP 交互回归（27 项断言）
```

## 设计约定

- **壁纸负责氛围，窗口永远是纸白**：细描边、克制阴影、紧凑标题栏；换任何壁纸正文对比度稳定。
- **强调色朱砂 #C24E2B**，衬线数字（Georgia）只点缀日历，正文现代无衬线 15px。
- **窗口规则**：正文区可正常选字/编辑/勾选，只有标题栏起拖；边缘 14px 内轻吸附；
  左右至少露出 96px、标题栏永不出屏、底不压应用栏；收回保留内容/位置/大小。
- **持久化键** `deskHome.v1`（localStorage）：窗口布局、显隐、待办、便笺、壁纸选择。
