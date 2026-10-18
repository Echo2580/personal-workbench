# 个人工作台 Windows 首版 · 产品、架构与 UI 规格

日期：2026-10-15。交付对象：在新会话中实现项目的开发者与 AI。

本文件记录本次用户确认的产品范围，以及据此提出的工程设计。正式产品代码尚未实现。配套文件为 `02-实施计划.md`、`03-新会话执行指令.md`；`04-UI设计预览.html` 是独立设计参考，不是产品实现或测试结果。

## 1. 目标与权威依据

产品是个人工作台：把个人学习、工作中需要的小工具收拢到一个可持续扩展的入口。首个业务模块是“项目集中＋启动器”。本次交付工作台公共外壳与这个完整模块，其他业务功能预留入口和代码接入位置。

首版成功意味着：用户双击进入工作台，能够发现、查找、配置和运行自己的项目；需要键盘输入的项目可以在独立终端使用；用户能看见所管理命令的运行状态并停止它们。

需求来源：

- [仓库 README](https://github.com/Echo2580/personal-workbench/blob/main/README.md)。
- [JTBD 与 Pre-mortem 基线](https://github.com/Echo2580/personal-workbench/blob/main/docs/JTBD%E4%B8%8EPre-mortem%E5%88%86%E6%9E%90.md)。
- [项目集中＋启动器 #1](https://github.com/Echo2580/personal-workbench/issues/1)、[项目预期 #3](https://github.com/Echo2580/personal-workbench/issues/3)、[待办＋日历 #4](https://github.com/Echo2580/personal-workbench/issues/4)。
- 当前会话用户的明确选择，尤其是下表两项对旧范围的修订。

### 1.1 用户已确认的决策

| 项目 | 本次确认 |
|---|---|
| 产品层级 | 工作台本体＋多个可增加的功能模块 |
| 本次范围 | 工作台公共外壳＋完整启动器；其他功能预留位置 |
| 默认页面 | 工作台首页，展示各功能入口 |
| UI | 浅色、简洁、偏效率工具；旧原型仅供参考 |
| 系统 | 仅 Windows |
| 安装运行 | 首次安装 Python 和依赖，之后双击启动 |
| 配置界面 | 加入扫描目录设置页与配方编辑抽屉 |
| 进程管理 | 加入进程跟踪与停止功能 |
| 管理边界 | 管理本工作台启动的命令及其子进程；IDE、文件夹、网页是打开动作 |
| 终端交互 | 命令项目启动独立终端，网页不内嵌终端 |
| 关闭网页 | 服务和项目继续运行 |
| 主动退出 | 提示运行中项目，确认后停止它们再退出 |
| 真实验收根目录 | `D:\AI实训project\llm` |
| 项目组织 | 展示有项目标识的独立目录；独立前后端分别列出；章节练习可手动添加目录 |

旧文档中“不做 GUI 配置器”“启动后不跟踪进程”已被本次用户选择修订。实施时应同步更新仓库对应说明，保留修订依据。云同步、插件系统和其他业务模块仍不进入本次范围。

### 1.2 本方案作出的工程决策

下列内容是设计方案，不应表述成用户过去已指定的技术细节：Python 3.12+、FastAPI、原生 JavaScript ES Modules、本地 TOML 配置与 JSON 缓存、Windows Job Object 管理命令树、默认扫描周期 15 秒、同项目单命令实例、默认端口区间和本文件的 UI 尺寸。

这些决定围绕已确认目标形成一套可直接实施的规格。实现发现不可行时，要指出具体证据与影响，再向用户询问实质性变更；不要静默改产品行为。

## 2. 本次交付与范围

### 2.1 必须完成

- 工作台公共外壳、独立首页、统一导航、公共反馈组件和设置页。
- 项目模块：扫描、自动发现、项目列表、搜索、筛选、排序、手动添加目录。
- 自动识别、配方预览、多配方、选择主配方、编辑保存、恢复自动识别。
- 命令启动、独立交互终端、真实进程状态、重复启动保护、停止命令树。
- IDE / 文件夹 / URL 的打开动作。
- 首次安装、双击入口、单实例、端口冲突处理、主动退出流程。
- 本地持久化、错误恢复、针对核心行为的测试和实测记录。
- 文档与旧范围同步；交接、运行说明、验收记录。

### 2.2 预留内容

首页和侧栏预留“快捷导航”“待办与日历”，名称依据现有 Issues。它们带“规划中”标识，显示说明但不可进入业务页面。占位项目通过同一份模块目录生成，不能在首页和侧栏各硬编码一份。

代码上保留模块登记、独立路由、独立页面、可选摘要和设置挂接点。首版不实现动态插件加载、插件市场、远程代码或通用工作流引擎。

本次不实现独立待办、提醒调度、日历、云同步、账号、多设备同步、EXE 打包、网页终端、外部程序接管，以及同一项目多服务编排。前后端分别启动，数据库等外部服务按原项目环境准备。

## 3. 真实项目情况与识别范围

本轮只读检查发现以下代表性项目。下面是文件证据，不表示已验证运行成功。

| 路径 | 已读取的运行依据 | 规格中的处理 |
|---|---|---|
| `D:\AI实训project\llm\werewolf` | README 给出 `python main.py --players 7`；目录有 `main.py` | 识别 Python 入口；可编辑参数；保留终端输入 |
| `D:\AI实训project\llm\todo-cli` | README 给出 `python todo.py` | 不能只认识 main.py；需要识别明确的 Python 可执行入口 |
| `D:\AI实训project\llm\周测4` | README 给出共享环境 `D:\AI实训project\ai2026-lg\Scripts\python.exe news_agent.py` | 支持全局默认解释器与每配方覆盖；验证解释器存在，不自动改环境 |
| `D:\AI实训project\llm\周测5.1` | package.json 有 `start: node src/server.js` | Node 配方选择 start；不猜 MySQL 连接和凭据 |
| `D:\AI实训project\llm\周测5\book-admin\frontend` | package.json 有 dev/start | 作为独立 Node 项目；默认优先 dev |
| `D:\AI实训project\llm\周测5\book-admin\backend` | package.json 有 dev/start 和数据库脚本 | 作为独立 Node 项目；数据库初始化不自动执行 |

README 是人工核对线索，不是可直接执行的指令来源。识别器不自动运行 README、安装依赖、导入目标 Python 包或读取密钥文件。

### 3.1 扫描行为

1. 配置至少一个根目录后开始扫描；应用启动自动扫描；之后每轮完成后间隔 15 秒进行下一轮；手动“重新扫描”可提前触发。
2. 同一时刻只执行一轮扫描；重复请求返回现有任务 ID，不叠加全目录扫描。扫描在工作线程执行，API 和进程操作保持可用。
3. 默认根目录最大深度 5，根自身为深度 0；目录预算 10000 个。超过预算或深度保留已发现结果并明确给出范围受限信息。
4. 默认跳过 `.git`、`.venv`、`venv`、`node_modules`、`__pycache__`、`dist`、`build`、`coverage`、`.workbuddy`、`.claude`、`.qwen`、`.idea`、`.vscode`、`logs`、`daily_reports`。扫描器可观察 `.git` 是否存在，但不进入其内部。
5. 不跟随目录符号链接和 junction。用户填写的根目录若本身是链接，提示填写实际目录，避免不透明扩大范围。
6. 用规范化绝对路径去重，处理盘符大小写和重叠根目录。同名不同目录是不同项目。
7. Python / 普通 Node / 静态项目识别成功后，默认不再把其内部目录识别成新项目，避免把 persona、coverage 和 src/pages 再列成项目。
8. package.json 明确声明 workspaces 时，继续检查其列出的本地工作区；分别登记实际有独立标识的子项目，不执行工作区脚本。
9. 读取入口标识和有限的顶层文件；单文件读取上限 1 MiB。损坏、超限或无权限文件记录为警告，不中止整轮。
10. 对可正常扫描的根目录，完整新结果替换该根对应的旧发现结果；根目录本轮不可访问时保留旧结果并标记“目录不可访问”，不误判为用户删除了全部项目。
11. 自动发现项目被删除后从清单移除，但保留人工覆盖和历史，防止临时移动造成配置丢失。运行中的项目即使路径失效也保留临时卡片以提供停止操作。

### 3.2 首批识别规则

| 类型 | 项目标识 | 自动配方 |
|---|---|---|
| Node | 项目根 package.json；或根目录无 package.json 时的单一 Node 入口（server.mjs / server.js / server.cjs / app.js / index.js / main.js） | scripts 优先级 dev > start > serve > preview；无脚本时按框架配置（vite / next / nuxt / astro / svelte / angular）→ package.json main → 单一入口推断；包管理器同前 |
| Python | pyproject.toml 的项目定义；任意顶层 `.py` 的明确 main guard；Django 顶层 manage.py；或 requirements(.txt/-dev.txt)＋README 的包目录 | AST 静态检查 `if __name__ == '__main__'`，不执行代码；单入口生成运行配方，多入口要求选择；Django 生成 `python manage.py runserver`；requirements 兜底只建项目、入口由用户选 |
| Go | go.mod，且根目录或 `cmd/<子目录>` 内存在 package main | `go run .` 或 `go run ./cmd/<子目录>`；只有 go.mod 的库不建项目 |
| Rust | Cargo.toml 且存在 src/main.rs | `cargo run` |
| 静态网页 | 顶层 index.html 或其他 .html（测试/覆盖率报告类文件名除外），且不归属上述项目 | 用默认浏览器打开该文件（项目目录内 .html，服务端校验）；多个 html 优先 index.html，否则按名称取第一个 |
| 手动目录 | 用户通过“添加项目”给出目录 | 总有打开文件夹动作；命令或网页配方由用户补充 |

Python 解释器优先级：项目 `.venv\Scripts\python.exe` → 项目 `venv\Scripts\python.exe` → 用户在设置中指定的默认解释器 → PATH 上可用的 python.exe。不得把工作台自己的专用虚拟环境默认为所有项目环境。找不到解释器时保留项目并明确提示配置。

只存在 requirements.txt 或章节练习 `.py` 的目录：有 README 且有依赖清单时按 Python 项目建卡（入口需手选）；测试/覆盖率报告类 HTML 不建项目。扫描根目录若只由弱证据（html / 单入口 / requirements）命中，仍继续下钻，避免整个扫描根被单个文件坍缩成一个项目而吞掉子项目。自动配方的“打开文件夹”兜底不计入运行配方识别成功率。

手动添加可接入章节目录。一个目录有多个脚本时，用户在配方抽屉中选择或填写具体命令；同一目录的多个入口仍属于同一个项目，不把每个 `.py` 各建一个项目。

## 4. 配方、配置与数据

### 4.1 配方种类

| kind | 字段 | 行为与状态 |
|---|---|---|
| command | 原生命令 program＋args，或手动 shell_command；cwd | 独立终端启动，跟踪命令树，可停止 |
| app | executable＋args；cwd | 打开指定应用，显示打开结果，不追踪应用 |
| directory | target | 打开文件夹，不追踪窗口 |
| url | target | 打开 http/https URL 或已识别静态 index.html 文件，不追踪浏览器 |

一个项目可以有多条配方和恰好一个主配方。自动生成配方使用稳定 ID，例如 `run-dev`、`run-python`、`open-directory`；手工新增使用随机 UUID。

默认主配方：可识别 command → 静态文件打开 → 打开文件夹。按钮文案根据配方为“启动项目”“打开网页”“打开文件夹”或“打开应用”，不能所有动作都叫启动。

一个项目同一时刻最多一个受管理 command 运行；打开类动作可以并行。重复启动或尝试另一 command 返回冲突并指向现有运行，页面提供先停止当前运行的操作，不启动第二份。前后端已分别列出，可各有一份运行。

### 4.2 本地保存位置

使用 `%LOCALAPPDATA%\PersonalWorkbench\`，不把个人目录和配方写入公共仓库。测试显式设置 WORKBENCH_DATA_DIR 到临时目录，生产默认值保持不变。

```text
PersonalWorkbench/
  settings.toml          # 扫描根目录、默认解释器、扫描参数
  projects.toml          # 手动添加目录与用户配方覆盖
  cache/projects.json    # 可重建的自动扫描结果
  history/projects.json  # 最近启动/打开与结束记录，最多 500 条
  history/approvals.json # 已确认配方的内容指纹
  runtime/instance.json  # 当前服务实例信息；不是项目进程恢复数据库
  logs/service.log       # 服务自身错误和操作结果，滚动大小限制
```

配置使用 TOML，GUI 通过 tomlkit 读写并保留未修改部分；缓存和历史使用 JSON。首版不需要数据库。先写同目录临时文件再原子替换，配置修改前保留上一份有效备份。

源代码中的默认扫描根目录为空。实施者应在当前电脑的本地设置中接入已授权根目录 `D:\AI实训project\llm`，不得将该路径硬编码进公开默认值。

### 4.3 最小数据契约

- `Project`：id、name、path、type、discovered_at、availability、recipe_source、recipes、primary_recipe_id、last_action_at、active_run。
- `availability`：available / missing / root_unavailable。`recipe_source`：auto / manual。
- 项目 ID 为规范化绝对路径 UTF-8 的 SHA-256 完整十六进制串。手动与自动发现同一路径合并，手动加入状态保留。
- `Recipe`：id、label、kind、cwd、program、args、shell_command、target。command 必须在 program＋args 与 shell_command 中恰选一种；不同 kind 只接受其适用字段。
- `Run`：id、project_id、recipe_id、service_instance_id、status、created_at、started_at、ended_at、exit_code、exit_reason、error_code。运行句柄只存在内存，PID 不是授权凭证。
- 时间以带时区的 UTC ISO 8601 保存，UI 按用户本地时区显示；相对时间有完整时间提示。

settings.toml 初始字段：schema_version=1、roots=[]、default_python=""、scan_interval_seconds=15、max_depth=5、max_directories=10000、excluded_names 为 3.1 列表。端口属于服务启动配置，不在首版设置页提供网络配置器。

projects.toml 保存 schema_version=1、manual_projects 数组，以及以 project_id 为键的 overrides 表。每个 override 保存 path、完整用户 recipes 数组和 primary_recipe_id。自动配方不复制进该文件，直到用户首次保存覆盖。

合并规则：当前有效自动识别结果 → 同 ID 的完整人工覆盖优先。扫描不覆盖人工配方。恢复自动识别只删除当前项目覆盖，界面先列出将丢弃的自定义内容并确认；手动项目的目录记录仍保留。

配置读响应包含 revision（该文件内容 SHA-256），保存通过 If-Match 携带 revision；冲突返回 409，保留用户草稿，提供重新载入。写入做最小结构和路径检查，不搭建通用配置校验平台。

手动文件修改在每轮扫描前重新读取；解析失败保留原文件和上次有效显示，页面给出文件名及行列。新启动暂不可用，已有运行仍可停止；修复后自动恢复。GUI 保存不能覆盖无法解析的外部修改。

## 5. 命令执行与生命周期

### 5.1 执行策略

- 自动 Python 配方使用明确 executable＋args；cwd 单独传递，不拼入 shell 命令。Python 进程设置 UTF-8 输出环境。
- Node 使用固定脚本名 dev/start 与选定包管理器；必须处理 Windows `.cmd` shim。脚本名来自允许字段，不把目录、项目名等插入 shell 文本。
- 用户手改的 shell_command 是明确保存的命令文本，通过固定 cmd.exe `/d /s /c` 执行；GUI 显示命令语法为 Windows CMD。程序生成的原生命令编辑为文本后，明确保存为手动 shell 命令。
- 确认标记基于配方内容指纹，包含 kind、命令、参数、解释器、cwd 和目标。首次执行与内容变化后确认；后续相同配方一键执行。确认结果在该用户本地保存，不能只信任浏览器布尔值。
- 启动前检查项目目录、cwd、解释器或应用路径、URL scheme；路径失效、工具缺失等错误带解决动作。
- 页面只提交项目 ID、配方 ID 和内容指纹，不能向启动接口临时传入任意命令或目标路径。
- 打开类 URL 仅允许 http、https，或项目目录内已存在的 `.html` 绝对路径（保存与执行时都校验 resolve 后仍位于项目根目录）；拒绝 javascript、项目外 file URL 和自定义协议。

### 5.2 Windows 进程管理

使用 pywin32 封装 Windows Job Object。每次 command 一个 Job：先创建挂起状态的进程及独立控制台，加入 Job 后再恢复；分配失败则结束挂起进程并返回失败，不退化成无法停止的后台程序。

Job 设置 KILL_ON_JOB_CLOSE，且 Job 句柄不被子进程继承。它解决 Node watcher / npm / Python 子进程遗留，也使服务异常退出后的行为明确。系统能力与强制终止语义依据 [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)、[TerminateJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject)。

管理器每 500ms 检查 Job 活动进程数。根进程退出而 Job 仍有进程时仍显示运行中；Job 归零后结束。exit_code 仅表示入口进程退出码，不伪称检查了所有子进程业务结果。

停止调用 TerminateJobObject，再确认 Job 归零并关闭资源。用户停止的原因优先于因此产生的非 0 退出码，状态记 stopped。它是结束命令树，不保证第三方程序执行优雅关闭回调。首版不实现通用优雅退出协议。

command 保留独立控制台的标准输入输出，支持 Todo CLI 和狼人杀输入；不将其重定向成无输入的后台任务。终端输出在终端查看，服务只记录启动、停止和退出结果。用户关闭项目终端后，管理器照实际状态更新。命令结束时其控制台可以关闭；首版页面不承诺提供 stdout/stderr 回放，也不能将入口退出码包装成已获取完整错误堆栈。

打开应用、文件夹、网页不进入这些 Job。首版不按程序名称查杀，不从历史 PID 恢复接管外部进程。

### 5.3 状态机与反馈

```text
launching -> running -> stopping -> stopped
    |          |
    |          +-> exited (入口退出 0 且 Job 归零)
    |          +-> failed (入口非 0 且 Job 归零)
    +-> failed (创建/分配/恢复失败)
```

单次很快结束的脚本可以从 launching 直接进入 exited/failed；不能强行展示一段假的运行动画。

卡片状态文案：未运行、启动中、运行中、停止中、已停止、已结束、启动失败、异常退出。运行中仅表示受管理进程仍存在，不代表 HTTP 已就绪或业务成功。

命令运行中主按钮显示“运行中”并禁用重复启动，旁边显示“停止”；打开文件夹、IDE、网页配方保持可用。打开类动作成功使用“已请求打开”，不改变项目命令状态。

### 5.4 服务生命周期

- 单用户单实例，使用命名互斥体。instance.json 记录 PID、启动时间、端口、服务实例 ID 与本地会话令牌。
- 再次双击时通过实例验证复用服务并打开首页，不能只发现端口有响应就认为是工作台。
- 默认尝试 127.0.0.1 的 17843–17852，逐个绑定，全部占用则显示清晰错误。禁止自动杀占用端口的其他程序。
- 必须确认服务就绪再打开浏览器；超过 10 秒显示启动失败与日志位置；失败后释放互斥体。
- 浏览器关闭不触发服务退出。
- 点击“退出工作台”：无运行任务时确认退出；有任务时列出项目名，按钮为“取消”“停止项目并退出”。成功停止全部后关闭服务，失败时保留服务与失败任务信息。
- 服务异常退出会因为 Job 句柄关闭结束其管理的命令树。重启后历史中未完成运行标记为 interrupted，不展示成仍在运行，不按旧 PID 停止程序。
- Uvicorn 生产模式单 worker、关闭 reload；开发重载会结束受管理运行，必须在开发说明写明。

## 6. 前端 UI 设计

### 6.1 信息架构与公共外壳

```text
个人工作台
├─ 工作台首页              #/                 默认进入
├─ 功能
│  └─ 项目启动器           #/projects         本次完整实现
├─ 规划中
│  ├─ 快捷导航             无业务路由
│  └─ 待办与日历           无业务路由
└─ 设置                    #/settings
   ├─ 扫描目录
   ├─ 项目默认环境
   └─ 关于与退出
```

桌面左侧固定 224px 导航，上方产品名；右侧为 64px 公共顶栏＋页面内容。顶栏显示当前模块及服务连接状态；扫描按钮属于项目页。设置和退出在侧栏底部，名称与状态同时出现，不依赖图标猜测。

模块清单驱动首页、侧栏和可用路由；公共外壳不包含“假定所有模块都有项目路径、配方、运行状态”的逻辑。

### 6.2 视觉规范

| 项目 | 规范 |
|---|---|
| 页面底色 | #F6F8FC |
| 面板 | #FFFFFF |
| 侧栏 | #F0F3F9 |
| 正文 | #172033 |
| 次要文字 | #56657B；禁止把重要路径和状态做成低对比灰 |
| 主色 | #2457DE；用于选中项、主动作、焦点 |
| 分隔线 | #DCE2EC |
| 成功 | #067647 / 浅底 #ECFDF3 |
| 错误 | #B42318 / 浅底 #FEF3F2 |
| 字体 | Segoe UI、Microsoft YaHei UI、系统 sans-serif；命令和路径用 Cascadia Code / Consolas |
| 字号 | 页标题 28/36，区标题 18/26，正文 14/22，辅助 12/18 |
| 间距 | 4、8、12、16、24、32、40px |
| 圆角 | 输入与按钮 8px，面板 12px；状态标签小圆角 |
| 阴影 | 日常面板以边线为主；抽屉与悬浮菜单使用轻微带偏移阴影 |
| 图标 | 一套线性 SVG，24px viewBox、统一笔画；每个图标按钮有可访问名称 |
| 动效 | 150–200ms 的状态与抽屉过渡；减少动态效果偏好下关闭非必要过渡 |

离线可用，不依赖在线字体、CDN、远程图标或图片。正文/控件文字对比度至少 4.5:1；焦点始终可见。状态用文字＋图标/色彩表达。

### 6.3 工作台首页

页面标题“工作台”，说明“常用工具，从这里开始”。主要内容是功能入口，首页不堆叠启动器的完整列表。

布局：左侧主要区域展示“项目启动器”可用入口，显示来自真实摘要的项目数量、运行中数量和最近扫描结果；右侧窄栏显示最多 4 个最近使用项目，点击进入项目页并定位该卡片。没有历史时解释记录会在实际使用后出现。

下方为“规划中的功能”两条紧凑行：快捷导航、待办与日历，附具体用途和“规划中”。不显示假任务、假日历或假使用统计。首个可用模块获得明显主次，预留位置保持可见但不抢占主操作。

首次使用没有扫描目录时，模块入口仍可进入，摘要显示“尚未配置扫描目录”；主动作“设置扫描目录”进入设置。当前电脑由实施者接入根目录后展示真实扫描结果。

### 6.4 项目启动器页

从用户原型保留：项目卡片、清楚的名称与路径、搜索筛选、配方展开、编辑抽屉。新增公共侧栏，以符合工作台层级。

页面头部：标题“项目启动器”，副标题显示扫描根目录数量、项目数、运行中数；右侧“添加项目”“重新扫描”。扫描中禁用重复请求并显示当前阶段，保留已有清单可操作。

工具栏：项目名称或路径搜索；类型筛选（全部 / Python / Node / 网页 / 其他）；排序（名称 / 最近使用）。搜索不区分大小写，过滤后显示匹配数量；清空搜索可恢复结果。

卡片网格默认两列，卡片独立高度，align-items:start。每张卡片按如下顺序：

1. 类型图标、项目名、类型、运行状态。
2. 完整路径的单行省略显示、悬停完整路径、复制路径按钮；无 Git 分支与未经定义的“最近修改”指标。
3. 配方来源、上次使用时间；路径失效或解释器缺失时展示具体问题。
4. 合适文案的主动作；运行时显示停止操作；配方展开按钮显示真实数量。
5. 展开区域逐条显示名称、类型、实际命令/目标、主配方标记和执行动作，底部“编辑配方”。

一次最多展开一张卡片；展开不会把邻卡拉成同高。路径和命令可复制；长项目名最多两行，不能挤掉状态。主按钮宽度适中，避免每张卡片底部大面积高饱和色条。

停止只作用于当前卡片对应 active_run；不能按项目名搜索系统进程。快捷按钮打开文件夹 / IDE 仍从配方 ID 执行。

### 6.5 配方编辑抽屉

从右侧打开，宽度 560px、最大占窗口减 24px，标题与项目路径固定，内容滚动，底部操作固定。背景使用轻遮罩，不以大面积模糊隐藏上下文。

- 字段：配方名称、类型、命令或目标、工作目录（command/app），主配方单选。
- command 显示完整命令；自动原生命令给出解释器及参数摘要，进入手改时提供可编辑的一行 Windows CMD 命令。
- app 的参数为逐项输入，数据按数组保存，避免 Windows 参数引号歧义。
- 提供添加配方、删除配方；最后一条配方不能删除；删除主配方后必须选择新主配方。
- 保存前验证名称、字段组合、cwd 是否有效、目标 scheme 与主配方唯一性；错误贴近字段。
- 默认工作目录为项目根目录。目标明确允许绝对路径；手动命令由用户决定，不自动从项目 README 提取执行。
- 顶部提示“自动识别＋人工覆盖”的保存关系；自动扫描不会撤销编辑。
- 底部：恢复自动识别、取消、保存。未保存关闭时提示“放弃修改 / 继续编辑”；保存冲突保留草稿。
- 运行中的 command 不允许编辑该运行所用配方或改变主命令，提示先停止；打开类配方允许编辑。恢复自动识别在项目有 active_run 时不可用。

### 6.6 设置页

第一组“扫描目录”：目录列表、可访问状态、删除；新增为完整路径文本输入和“添加目录”，帮助文案说明会递归发现项目。目录已存在或被其他根目录覆盖时提示并去重，不创建重复项。

第二组“项目默认环境”：可选 Python 解释器路径、验证按钮与结果；说明项目自身 .venv 优先。默认值留空时按 PATH 查找；界面不要把“工作台运行 Python”混成“项目运行 Python”。

扫描周期与深度显示默认值，首版可以放在可折叠“扫描选项”内编辑；只接受周期 5–300 秒、深度 1–10；总目录预算保持工程默认，不做全参数面板。

第三组“关于”：服务版本、当前本地数据目录、打开数据目录、退出工作台。配方、根目录和解释器保存后给明确反馈，返回项目页可看到更新。

### 6.7 完整状态清单

| 场景 | 页面行为 |
|---|---|
| 首次无目录 | 说明用途，提供设置入口 |
| 已配置无项目 | 显示扫描范围，提供添加项目与调整目录 |
| 搜索无结果 | 显示当前查询和清空搜索操作 |
| 首次加载 | 与卡片结构一致的骨架，不填假项目 |
| 扫描部分失败 | 保留成功结果，列出失败目录及原因 |
| 配方待确认 | 展示命令、cwd 和操作种类，确认后执行 |
| 缺少解释器/工具 | 具体错误＋编辑配方或设置入口 |
| 进程已存在 | 定位现有运行；避免二次启动 |
| 命令非 0 退出 | 显示异常退出与入口退出码；终端为输出查看位置 |
| 配置保存中/失败/冲突 | 防重复提交，保留编辑内容与恢复路径 |
| 服务断连 | 顶部持续提示，禁用启动/停止；连接恢复后重新获取真实状态 |
| 退出有运行任务 | 确认列出受影响项目；全部停止后退出 |

反馈消息通常 4–6 秒；需要用户修复的问题在页面持续显示，不能只闪一下 toast。用户数据以文本节点渲染，禁止拼入未经转义的 innerHTML。

### 6.8 响应式与键盘

- 1440/1280 宽桌面保留完整导航与双列项目；1100 以下侧栏缩为带提示的图标栏，内容仍有明确标题。
- 卡片最小约 380px，通过 auto-fit 决定列数；低于可容纳两列时改为单列。
- 窄窗口侧栏折叠为按钮打开的导航面板；抽屉改为近全宽。该适配服务 Windows 浏览器窗口缩放，不扩展移动端产品范围。
- Tab 顺序按可见布局，所有控件有 label；搜索 Esc 可清空；抽屉 Esc 按未保存流程关闭；焦点受约束并在关闭后返回触发按钮。
- 保留浏览器 200% 缩放下的核心操作，长路径不造成整体横向滚动。

## 7. 模块架构与技术栈

### 7.1 技术栈

- Python 3.12+；FastAPI、Uvicorn、tomlkit、pywin32。
- 前端 HTML/CSS/原生 JavaScript ES Modules，按页面和模块拆分；JSDoc 定义接口，不引入构建器。
- pytest 验证业务和 Windows 进程管理；浏览器测试使用 Python Playwright，测试依赖与运行依赖分开。
- 项目启动不要求安装 Node。Node 项目自身运行仍依赖其原有 Node 环境。
- 安装时锁定经过验证的直接与传递依赖版本，记录实际 Python 与库版本。不开启自动升级依赖。

采用原生前端的原因是首版页面数量可控、公共外壳接口可明确，且能直接由 Python 服务提供，安装流程只需要 Python。多模块能力通过目录与注册契约保证，不能依赖一个不断增长的 app.js。

FastAPI 可以提供本地静态资源和分模块路由：[StaticFiles](https://fastapi.tiangolo.com/tutorial/static-files/)、[APIRouter](https://fastapi.tiangolo.com/tutorial/bigger-applications/)。Python 3.12 提供 junction 路径识别接口：[pathlib](https://docs.python.org/3.12/library/pathlib.html#pathlib.Path.is_junction)。

### 7.2 职责划分

```text
应用组装层
  ├─ 核心：服务生命周期、配置文件读写、模块契约、API 边界
  ├─ 项目模块：扫描、配方、项目数据、命令管理、项目 API
  └─ 静态资源：公共外壳、首页、设置挂接、项目页面
```

公共核心不能导入项目扫描器、配方结构或进程状态来判断其他模块。模块注册表是组装位置，可以导入各模块公开入口。首页通过通用摘要契约获取数据显示，不直接调用扫描器。

后端 ModuleDefinition：id、title、description、icon、route、status（available/planned）、router（可选）、summary_provider（可选）。项目模块公开其 definition，组装层登记。规划中模块仅有元数据。

前端页面生命周期统一为 `mount(container, context) -> cleanup()`；context 包含 api、navigate、notify、signal。切换路由调用 cleanup 并 abort 请求，清理轮询、事件监听和抽屉。

前端 loader map 只从 module_id 定位模块公开入口；名称、说明、排序和可用性来自服务返回的统一模块目录。新增功能只需新增模块目录，在后端注册表和前端 loader map 挂接，再新增独立路由与页面，不改 projects 内部。

### 7.3 建议目录

下面路径均相对正式仓库 `D:\AI实训project\个人工作台\wb`，不是本交接包目录。

```text
app/
  main.py
  launcher.py
  module_registry.py
  core/
    contracts.py
    config_files.py
    instance.py
    security.py
    shutdown.py
  modules/projects/
    module.py
    models.py
    settings.py
    scanner.py
    detectors.py
    recipes.py
    store.py
    service.py
    runtime.py
    windows_job.py
    actions.py
    router.py
  web/
    index.html
    styles/tokens.css
    styles/shell.css
    core/api.js
    core/router.js
    core/dom.js
    core/notifications.js
    core/module-loaders.js
    shell.js
    pages/home.js
    pages/settings.js
    modules/projects/index.js
    modules/projects/api.js
    modules/projects/page.js
    modules/projects/card.js
    modules/projects/recipe-editor.js
    modules/projects/settings.js
    modules/projects/styles.css
tests/
  unit/
  integration/
  windows/
  browser/
  fixtures/
scripts/setup.ps1
scripts/start.ps1
start.cmd
pyproject.toml
requirements.lock
requirements-dev.lock
docs/architecture.md
docs/devlog.md
docs/acceptance.md
```

runtime.py 管理业务锁和运行状态，windows_job.py 专管系统句柄，actions.py 处理打开动作。禁止把扫描、命令执行、GUI 表单和 API 全堆进 main.py。

## 8. API 与本地安全边界

服务同源提供网页和 API，不开启宽泛 CORS。绑定 127.0.0.1，校验 Host 与变更请求 Origin。实例启动生成随机会话令牌，所有业务 API 请求携带 `X-Workbench-Token`。静态页面的同源 bootstrap 返回当前令牌，跨站请求不得读取或触发操作。

API 前缀 `/api/v1`；以 Pydantic 定义请求和响应。统一错误结构：`{error:{code,message,details,recovery_action},request_id}`。列表空结果仍是正常 200；参数错误 422，找不到 ID 为 404，冲突 409，来源或令牌不符 403。

| 方法与路径 | 契约 |
|---|---|
| GET /healthz | 最小服务身份与就绪信息；不返回路径、令牌或配置 |
| GET /api/v1/bootstrap | 同源加载令牌、实例 ID、版本、统一 modules 列表和摘要 |
| GET /api/v1/instance | 需令牌；供入口验证 instance.json 对应实例 |
| GET /api/v1/projects | projects、scan 状态、warnings；active_run 带真实状态 |
| POST /api/v1/projects/scan | 202＋scan_id；已有扫描则返回同一 ID |
| POST /api/v1/projects/manual | `{path,name?}`；检查存在与去重，返回项目 |
| DELETE /api/v1/projects/{id}/manual | 仅移除手动登记，不删除磁盘文件；自动发现项目仍保留 |
| GET /api/v1/projects/{id}/recipes | 生效配方、来源、文件 revision |
| PUT /api/v1/projects/{id}/recipes | 完整配方＋primary_recipe_id，If-Match；返回新 revision |
| DELETE /api/v1/projects/{id}/override | If-Match；清除当前项目覆盖，重新计算自动配方 |
| POST /api/v1/projects/{id}/recipe-approval | `{recipe_id,fingerprint}`；确认当前内容，变化则拒绝过期确认 |
| POST /api/v1/projects/{id}/actions | `{recipe_id,fingerprint}`；command 返回 202＋run，其余返回打开请求结果 |
| POST /api/v1/projects/runs/{run_id}/stop | 需运行属于当前实例；幂等停止，返回真实状态 |
| GET /api/v1/projects/runs | 当前与最近运行状态；只查询本模块记录 |
| GET /api/v1/settings/projects | 根目录、解释器、扫描选项和 revision |
| PUT /api/v1/settings/projects | If-Match 保存项目设置，触发受控重扫 |
| POST /api/v1/settings/projects/validate-python | `{path}`；检查文件及短超时 `--version`，不运行目标项目 |
| POST /api/v1/system/open-data-directory | 打开固定本地数据目录，不接收任意路径 |
| POST /api/v1/system/shutdown | `{confirmed_stop_running:boolean}`；有运行且未确认返回 409＋列表；停止完成后安排退出 |

首次批准接口只写批准指纹，不自行执行；执行接口核对服务端保存的批准和当前配方指纹。前端原生文本渲染防止项目名进入 HTML；任何打开目录、应用或文件都从已保存配置查找，不能用查询参数提供任意磁盘路径。

页面可见时每 2 秒拉取状态；后台标签页降到 10 秒；断连指数退避至 30 秒，恢复后立即拉取。切换页面必须清理计时器。首版不引入 WebSocket。

## 9. 安装、文档与验证

### 9.1 安装与入口

setup.ps1 检查 Python 版本，在工作台仓库创建专用 .venv，安装锁定依赖，检查静态资源和 pywin32 可用性。不能向其他项目的环境安装工作台依赖。缺失 Python 时说明安装要求；网络失败显示真实错误，不继续假装完成。

start.cmd 为可双击入口，调用 start.ps1，后者使用已安装的专用 pythonw 启动后台服务入口；脚本处理中文和空格路径、日志、就绪等待和单实例。首次未安装时显示 setup 操作，日常不要求手动启动 Uvicorn 或输入地址。需要启动后台进程时保持服务窗口隐藏，项目的独立终端窗口按用户确认显示。

### 9.2 验收口径

1. 约 100 项目扫描 ≤5 秒：用固定的 100 项目测试目录测量，也测真实根目录；报告硬件、目录规模、限制和多次耗时，不将合成目录当真实识别率证据。
2. 自动识别率目标 ≥80%：先确认真实独立项目清单，再逐条判断无需人工修改能否形成正确运行配方；环境未就绪与规则不正确分开记录；不得剔除失败项目抬高指标。
3. 手改 ≤1 行、≤30 秒：入口猜错时修改命令字段或解释器，实际计时；新增复杂配方不混同这条指标。
4. 一键启动 ≤3 秒：分别记录点击至受管理进程产生、业务实际可用的时间。进程 running 不等于业务就绪；环境已准备的代表项目按原指标实测，没达到必须报告。
5. 新项目零登记：向已配置根目录放入支持类型，在最多一轮扫描周期＋扫描耗时内自动出现；用户无须点刷新。
6. 一键停止：验证受管理的父子进程全部退出，同名外部对照进程仍存活。
7. 独立终端：确认 Todo CLI 可输入；狼人杀命令能按用户选定参数交互。涉及 LLM、数据库或写入业务数据的真实验收单独记事实结果，不能用 fixture 代替。
8. 另一台电脑安装与接入 ≤30 分钟：需要组员实测；本机测试不能代签。
9. 两周内每周主动打开 ≥3 次且真实运行过项目：属于发布后的使用验收，交付当天不能提前写通过。
10. 可扩展性：在测试中登记临时新模块，确认路由、导航、首页、设置挂接有效，projects 内部文件不变。测试模块不进入发布产品。

### 9.3 完成定义

当核心自动化检查、Windows 进程集成、浏览器流程及当前电脑入口实测通过，可交付“本机可用首版”。组员测试、长期使用指标和需要真实外部环境的项目运行逐项标记待实测及原因，不伪称已全部验收。

共享解释器 `D:\AI实训project\ai2026-lg\Scripts\python.exe` 的文件存在性已只读验证。解释器库、真实 80% 识别率、数据库与 LLM 服务可用性，目前未验证；这些是实施期的可检测事项。若检测结果要求改变用户已确认的产品行为，应当时询问，而不是猜一个环境值。

历史文档的一周静态清单需求验证没有已完成证据。本交接不把它计为已完成；用户本次要求新会话实现项目，实施按本方案推进，发布后的真实使用指标继续如实记录，是否另行进行静态清单验证由发起人安排。

协作继续遵守：单线推进；由新会话收到用户明确实施授权后修改正式仓库；AI 不执行 git commit/push，只给发起人用途明确的 PowerShell 命令。


## 2026-10-16 用户确认的增量：从工作台移除

所有项目卡片增加“从工作台移除”，自动扫描与手动登记统一使用。仅隐藏所选项目，不触及磁盘文件、数据库或解释器；保留手动登记、人工配方和使用历史。重新扫描和重启后不再次出现，首页统计与最近使用同步隐藏。运行中必须先停止。确认框明示本地文件不受影响和设置恢复入口。

设置页增加“已移除项目”，显示名称、路径并支持恢复；恢复后依据当前扫描范围或已有手动登记重新显示。重新手动添加已移除目录时提示先恢复。projects.toml 增加以 project_id 为键的 removed_projects 表，记录 path、name、removed_at；旧配置向后兼容。新增 GET /projects/removed、DELETE /projects/{id}、POST /projects/{id}/restore，写接口使用 If-Match。本节修订原来仅能移除手动登记的 UI 边界，旧 manual 删除接口保留兼容。


## 2026-10-16 增量：自定义项目显示名称

自动扫描与手动项目卡片均支持“修改名称”，保存1–120字符的单行名称，去首尾空白，允许恢复默认。仅改变工作台显示，保留路径、项目ID、配方、批准、进程与历史；允许运行中改名。重扫、重启、移除再恢复后保留别名。首页、最近使用、搜索排序、移除列表和退出提示采用当前名称。使用独立project_names本地元数据与If-Match保护，冲突保留输入；不增加新依赖，不修改被扫描项目。
