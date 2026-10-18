# 开发记录

## 2026-10-15：基线与后端

正式仓库 main 的基线为 83ba3ce，原有未跟踪 `docs/AI交接提示词.md` 保留未改。建立 feat/windows-v1 分支，无提交或推送。读取适用指令及交接规格；未发现 AGENTS.md。用户明确修订 GUI 配置和进程管理范围，按原实施计划单线执行。

建立工作台专用 Python 3.12.7 环境。先写测试，再实现配置原子保存、备份、revision、安全边界、模块目录、扫描识别、人工覆盖、设置及批准 API。阶段测试 4、11、15 项通过。

Windows 实测纠正了 pywin32 无名 Job 参数（空字符串）以及测试键盘辅助程序自身的控制台/虚拟键码。TOML 可选字段省略 null，避免无效保存。真实只读扫描先发现 6 个目录，多入口与深度限制均保留证据。

用户要求暂停，写入 progress/resume 并清理测试进程，没有继续开发。

## 2026-10-16：恢复与交付实现

用户说“继续”，复核状态并重跑 19 项后端/Windows 测试通过。随后用户授权休息期间自主处理工程判断，将真实业务验收保留待本人接手。

完成原生 ES Modules UI：首页、统一导航、项目卡片、搜索筛选、配方抽屉、设置、批准/执行、真实运行轮询、停止、冲突草稿、断连恢复。没有演示数据进入 app。规划中模块由同一目录生成。

完成 pythonw 隐藏入口、命名互斥体、实例身份验证、端口顺延、退出确认、停止失败保留服务、安装脚本与实际依赖锁。Windows PowerShell 5.1 的原生参数引号问题由安装脚本实跑发现并修复。补充了 junction、Create/Assign/Resume 失败清理、真实 npm.cmd 树停止、服务异常退出、新模块接入和自动发现测试。

用户明确选择狼人杀 `main.py --players 7`。本机保存该配方及周测4 README 指定解释器，扫描根目录保存到 LocalAppData，未在代码默认值硬编码。没有安装或修改被扫描项目依赖，没有读密钥或执行真实业务项目。

## 审查与工程判断

- 排除 test_*.py、*_test.py、conftest.py 业务入口，避免 todo-cli 的测试运行器形成假多入口；真正多个业务入口继续要求选择。先有失败回归，再修复。
- 连接状态只在变化时发事件，保留轮询中的键盘焦点；会话变更后 GET 重新 bootstrap，不自动重放写操作。
- 运行快照排除旧 active_run/last_run，避免递归历史。
- 损坏 package.json 的非对象顶层不会中止整轮；实际文件读取大小有界，配置字段类型错误返回可修复错误。
- 无目录首页优先显示设置入口，不能把空扫描包装成已经配置成功。
- 公共关停从项目字段依赖改为通用回调，shell 从系统接口读取退出预览；新增模块不必修改 projects 内部。
- 慢模块动态加载结束后检查 AbortSignal，避免用户快速切换时由迟到页面覆盖当前路由。
- 使用现有仓库分支单线实施；按用户要求不引入并行实施、提交、推送或额外工作树。最终为作者自审，未做独立人工代码评审。

阶段完整测试曾得到 32、47 项通过。最终数量及最终命令结果以 acceptance.md 为准；阶段数字不替代交付验证。

## 保留的验收事项

真实项目的数据库、LLM 调用、目标依赖与业务就绪、真人编辑计时、鼠标双击体验、组员安装及两周使用记录留给实际使用者。浏览器和离线夹具结果不会代签这些指标。

## 2026-10-16：狼人杀首跑缺包修复

用户报告独立终端闪退。仅提取既有失败日志的 aborted 字段，确认 ModuleNotFoundError: No module named openai，系统 Python 3.13 无该依赖，入口退出1。现有共享环境 ai2026-lg 的 openai 为1.109.1，-B SDK导入与 -B main.py --help 均通过。

通过当前桌面服务配置API保存并回读确认狼人杀人工配方为共享解释器 + main.py --players 7。工具读取的本地实例记录/配置与运行服务一度不一致，因此本次以实际服务回读为生效依据；没有据此猜测或修改实例管理实现。未安装依赖、修改目标源码/数据库、读取密钥或重跑真实对局。清理了本次诊断产生的失败重复入口，保留当前服务。模型连通与完整交互需用户再次启动验收。


## 2026-10-16：项目移除与恢复

用户确认短设计后单线实施，保留已有全部修改。新增 API/浏览器行为测试，先观察缺失 API 的 404 和缺失按钮失败，再接入持久移除记录、服务端运行保护、恢复、卡片确认框和设置列表。配方与历史不清除；首页与列表共享过滤后快照。补充旧服务兼容提示与确认框固定 revision，防止轮询更新确认依据。

新增 7 个参数化后测试实例，最终全量 57 passed，78.31 秒；Python/JavaScript 语法、Ruff F/E9（含 scripts）和 pip check 通过。首次完整回归 55 passed、1 failed，旧控制台输入测试读到 ahello-console；没有修改或放宽该测试，单独复测通过，最终完整回归通过。额外字符来源未确定，保留首次 XML，不把首次结果写成全绿。

新增 scripts/verify_project_removal_ui.py：只读当前真实目录与配方，使用一次性数据目录进行移除/恢复，不执行真实配方；桌面 1440 与窄窗口 600 无横向溢出、无页面脚本错误。真实生产配置未替用户隐藏任何项目，截图在 gitignore 的 local-evidence 中。

初检正式服务有狼人杀活跃运行，因此保留旧服务并补兼容提示。后续检测活跃数为 0，保存当前服务配置快照，通过 confirmed_stop_running=false 的正常退出接口退出，再用隐藏生产入口加载新代码。回读移除接口可用、六项目完整、扫描设置一致、狼人杀配方完全保留，未启动真实项目。服务与工具磁盘 projects.toml 的版本差异再次出现；语义核对显示狼人杀一致，工具磁盘另有先前已授权的周测4覆盖，未借机改动实例管理或清除配置。快照与激活证据仅留本机。

最终交付复核：正式服务 /healthz ready=true，新移除列表接口可用，六项目、已移除0项；新服务的 projects.toml revision 与工具读取磁盘版本一致。未替用户选择移除项目，未提交或推送。


## 2026-10-16：新增启动失败反馈（待错误原文）

用户报告无法进入。现场复核正式服务在 17843 存活、实例文件身份与握手一致；start.cmd 返回0，重复隐藏入口返回0，没有新增服务或启动错误。真实浏览器进入首页、六项目列表与设置页成功，页面脚本错误0。日志只读到较早的08:18超时，不能将它认定为当前故障根因。已重新请求打开首页，未改代码、重装、清空配置或停止项目。已请求用户提供当前错误原文与报错发生在入口还是浏览器，反馈前不宣称修复。详细现场结果存本机 startup-diagnostic.json。


## 2026-10-16：收到超时截图并修复实例发现缺陷

截图确认弹窗为“现有工作台尚未就绪，超过10秒”。现场服务和握手当时正常，日志没有新的相应错误，不能从截图追溯当时具体是哪种元数据异常。结合此前观测的实例记录/实际服务不一致，增加独立 Windows 进程测试：实例文件缺失、错误令牌/ID、损坏 JSON 均在旧入口重现同款超时（3例），复制其他数据目录的有效实例记录则会被旧代码误认（1例）；冷启动删除实例文件后，旧就绪观察器会错误退出已可访问的服务（1例）。先观察以上失败后修复，没有把历史日志当作已确定的本次唯一根因。

修复为候选服务的令牌、身份、数据目录交叉校验与有界恢复；冷启动使用自身内存实例信息直接验证 HTTP。额外重定向测试先失败，再禁止握手跳转，避免转发令牌。六项新增回归通过。正式 start.cmd 与重复隐藏入口均正常复用原服务，六项目保持；未损坏生产实例记录来做测试，也未停止生产项目或重启服务。完整结果见本次验收附录。


## 2026-10-16：接入用户指定的 WorkBuddy2API

只读检查用户新增扫描目录下的README与app/start.bat，确认实际入口为Go二进制wb2api.exe -config config.json，bat附加pause。现有识别器不识别Go或任意bat，误将internal/panel/index.html当成独立静态网页。通过正常API手动登记真正的app目录，保存原生可执行程序/参数为主配方、7863/panel/为打开网页配方，并保留打开文件夹。读回与实际浏览器卡片/展开配方通过，未审批或执行真实业务，未改项目文件和凭据。原误识别panel卡片保留供用户自行从工作台移除。本机证据与截图见local-evidence/workbuddy2api-connection.json、screenshots/workbuddy2api-recipes.png；私有完整路径不写入公共默认值。


## 2026-10-16：项目名称编辑

按用户新增功能请求，在卡片增加修改名称与恢复默认；使用独立project_names元数据，与手动目录和配方分离，运行中改名不触发重启或重新批准。后端保证持久化、名称校验、版本冲突；前端支持Enter、取消、默认名称说明、错误保留草稿。浏览器先暴露输入框帮助文字混入无障碍名称，随后为输入设置明确aria-label，复测通过。

新增8项参数化后回归实例，全部先观察缺失行为失败，再实现。最终全量71 passed（116.44秒），静态/语法/依赖检查通过。实际正式服务编辑框打开/取消与1440、600布局检查通过，无脚本错误；没有为截图给生产项目填入演示别名。

加载前发现运行服务的项目配置与磁盘版本不同，尤其panel/周测4移除状态与WorkBuddy2API登记不同。未猜测成因，向用户列明影响并取得“保留磁盘最新设置（含WorkBuddy2API）”的明确选择。备份并验证配置后，通过不允许停止活跃任务的正常接口退出；当时无活跃项目。新服务回读5可见、3移除与预期一致，两份配置哈希未变，名称能力可用。未替用户实际改名，未执行git add/commit/push，原有交接文件保留。


## 2026-10-16：最新AI交接材料

用户要求交接给另一AI。只读核对正式仓库分支/HEAD/未提交状态、现有测试XML、服务项目状态、配置revision和桌面快捷方式；没有重跑pytest或执行真实项目。最新09:44快照4可见/4移除（用户后续隐藏周测4），服务与磁盘一致，WorkBuddy2API最近历史exited/0不代表业务验收。新建docs/交接中的项目交接说明和可复制提示词，README增加入口、resume增加最新快照、提交说明纳入新文档目录。旧AI交接提示词原文保留，强调旧边界过期、本地代码大部分未跟踪、不能仅从GitHub接手。未提交、推送或发送给其他会话。

## 2026-10-16：接手核对与真实业务验收（部分）

新接手 AI 按交接说明完成核对：分支 feat/windows-v1、HEAD 83ba3ce、未提交状态与交接一致；.venv Python 3.12.7、桌面快捷方式、服务 127.0.0.1:17843 均确认。发现 DSH 沙箱无法在仓库目录授予写权限，经用户批准后修复目录 WRITE_OWNER 权限（备份与回滚脚本在 docs/local-evidence/acl-recovery/）。本轮获得用户明确授权执行真实业务验收（第 1 项）：

- **WorkBuddy2API 通过**：用户已在工作台启动 wb2api.exe（active_run running），http://127.0.0.1:7863/panel/ 实际返回 200 HTML 页面，管理面板 HTTP 就绪确认。
- **werewolf 模型连通通过**：用已保存解释器 ai2026-lg 跑 `--players 6 --seed 42 --silent --no-postgame` 全 AI 冒烟局，完整对局结束，6 席共 26 次模型调用全部成功（墙上 224.6 秒）。仅终局保存复盘 JSON 时因测试沙箱无目标目录写权限报 PermissionError 退出码 1，属测试环境限制，非项目缺陷；对局本体与模型连通验证通过。7 人真人对局仍未代替用户执行。
- **周测5.1 HTTP + MySQL 通过**：npm run start 启动成功，/health 返回 200 {"status":"ok"}，首页 / 返回 200 且渲染出 MySQL 中的图书数据（如 BK0010）。验证后已停止测试进程。
- **todo-cli SQLite 部分通过**：在临时副本上完成 增/标记完成/删 CRUD 全流程通过；但生产 todo.db 当前写入报 "attempt to write a readonly database"，文件只读属性和 ACL 均正常，原因未查明（疑似外部进程持有只读句柄或其他锁定）。需用户确认后排查；未修改生产数据库任何字节。

环境观察：本轮 PowerShell 以 [System.Diagnostics.Process] 启动的子进程会随命令结束被终止，周测5.1 改用后台 cmd 方式验证。未提交、未推送，全部既有未跟踪文件保留。

## 2026-10-18：外壳按最终原型重做 + Snap2Todo 并入为原生模块（阶段 1、2）

用户提供 `最终原型/personal-workbench_home.html` 作为设计参考，要求"按原型重新生成首页"而不是简化版；随后要求把独立项目 Snap2Todo（`D:\AI实训project\截图转代办`）作为工作台原生模块并入，而不是两个壳子。

**阶段 1（外壳）**：
- 顶部/侧栏/首页三行仪表盘按原型重建：今日总览、天气卡（城市切换/逐时温度/湖面插画）、今日待办（筛选、进度条、侧滑详情）、网络梗词小报（换一批/弹窗）、常用入口、接下来（7 天日期条+日程）、随手记（内联编辑）、全局搜索（Ctrl+K）、新建待办弹窗、toast。
- 原型依赖 Tailwind CDN + Iconify。CSP（`script-src 'self'; style-src 'self'`）下不可用，故本地化：`tools/tailwind/`（构建输入）+ 提交 `app/web/styles/tailwind.css`（运行时零依赖），`app/web/core/icons.js` 提供 31 个内联 SVG 图标。禁用 preflight 后需手动补 transform 变量默认值与 `border-style`，否则抽屉不滑出、细线全部消失（已修）。
- 保留全部既有测试契约：可访问名称、`#content`/`#navigation` 等挂点、`moduleLoaders` 注入方式；4 处断言随 H1 改为「我的一天」同步更新。
- 独立核验智能体对照原型指出内容列被旧 `main{margin:0 auto}` 压缩（956→1220px）、根字号 14px 致 rem 缩水、600 下侧栏无关闭入口，均已修（`:root{font-size:16px}` + `body{font-size:14px}` 保持旧页面字号）。

**阶段 2（模块并入）**：
- `app/modules/tasks/` 承接 Snap2Todo 的 api/domain/services/storage（20 个上游文件逐字等价，仅 `app.` → `app.modules.tasks.`）；`module.py` 组合三组路由为无前缀 router，注册为 `tasks / 待办清单 / /tasks / available`。
- 数据根：`create_app` 注入 `app.state.data_root = <数据目录>/tasks`，模块首次写入才建目录。按用户决定**不迁移**源项目旧数据（源目录零写入，审计以时间戳验证）。
- 依赖：`requirements.lock` 增补 `httpx`/`httpcore`/`certifi`（model_adapter 模块级依赖）与 `python-multipart==0.0.20`（截图上传）；已安装进 .venv，`pip check` 干净。
- 测试：27 个测试文件迁入 `tests/tasks/`，node id 集合与源项目完全一致（469），断言零删弱；3 个 skip（1 个沿用源 skipif，2 个依赖源仓库路径并注明理由）。`pytest tests/tasks` = 466 passed/3 skipped；`pytest -q` 全量 = **537 passed/3 skipped**。
- 前端最小版 `app/web/modules/tasks/page.js`：列表/筛选/完成重开/删除/空状态/错误态；因上游无 `POST /api/v1/tasks`，创建只能走导入链路（阶段 4）。`core/api.js` 补 204 无内容响应处理。
- 独立验收审计：源项目零写入、数据隔离、9 条路由与 token 边界、依赖与 lock 一致、测试真实性均通过，**P0=0，条件通过**。已知 P1：未提交；老安装不重跑 `install.cmd` 会缺新依赖导致模块降级为「规划中」；源项目旧待办无迁移方案；新页面缺浏览器测试；首页 mock「今日待办」与真实模块待阶段 3 统一。

未提交、未推送；生产服务 17843 未重启，仍运行旧代码。

## 2026-10-18：首页「今日待办」接真实模块数据（阶段 3）

- 首页待办卡片从演示数据改为读 `/api/v1/tasks?status=all`：显示真实标题、截止/开始时间、执行要求条数、「待确认」标记；勾选完成走 `PATCH /api/v1/tasks/{id}` 并刷新，徽标、进度条、头部摘要随之更新。
- 首页不再自带「新建待办」表单和详情抽屉（编辑统一在模块页）：新建/添加按钮跳转 `/tasks`；快速输入「存为待办」把文本写入 `sessionStorage` 并在导入页自动预填到「粘贴文字」页签。
- 空状态区分「全部/进行中/已完成」，并提供「去导入通知」入口；读取失败有重试。
- 新增回归 `tests/browser/test_home_tasks.py`：注入 Mock 模型 → 走提取+确认建真实待办 → 首页断言标题/要求数/进度 → 勾选后徽标与进度同步。
- 全量回归 **538 passed / 3 skipped**（原 537 + 新增 1）。
- 已知边界：日程/梗词/天气/随手记仍是占位；提醒仍只在待办模块页打开期间有效（外壳层提醒未做）。

未提交、未推送。

## 2026-10-18：外壳层提醒（提醒从模块页上移到工作台）

- 新增 `app/web/core/reminders.js`：由工作台外壳发起提醒会话并每 5 秒轮询到期提醒，**任意页面都生效**；右下角固定卡片显示标题与提醒时间，提供「确认 / 稍后 / 查看待办」。
- 会话与去重：整个工作台只开一个 `POST /api/v1/reminder-sessions`；去重键用 `wb.` 前缀写 sessionStorage（与模块内原 `s2t:` 前缀区分）；服务重启导致会话失效时自动重开。
- 待办模块不再自己轮询：`createTasksApp(scope,{reminders:false})`，避免同一工作台开两个会话、弹两次提醒。
- 退出工作台时停掉轮询。
- 语义沿用源产品：提醒只在工作台打开期间有效；**会话开始前已到点的提醒不补发**（本轮实测踩到过一次，属契约行为，非缺陷）。
- 新增回归 `tests/browser/test_shell_reminders.py`：首页加载只发起 1 次会话，进入待办页后仍为 1 次。
- 全量回归 **539 passed / 3 skipped**。

未提交、未推送。

## 2026-10-18：整站视觉与信息架构统一

- 三套配色合一：`styles/tokens.css` 全局换成暖白/墨绿（项目页、设置页随之统一）；`modules/tasks/styles.css` 的 9 个主题变量重映射并替换硬编码蓝，待办页与外框一致。
- 页面骨架去重：待办页去掉自带顶栏里与外框重复的「本地运行中」状态和头像，只保留轻量步骤条并与内容区左对齐。
- 按键层级统一为规则：页面主操作=右上实心墨绿；次级=描边；辅助/破坏性=文字链接。移除首页卡片里与「新建待办」重复的「添加」按钮；列表视图自动隐藏「待办清单」按钮。
- 身份统一：侧栏/顶栏/移动端头像统一为「林」，窄屏隐藏重复头像。
- 验证：539 passed / 3 skipped；1440 与 600 无横向溢出、无 console 错误。

未提交、未推送。

## 2026-10-18：期 0 模型统一 + 期 1 手动新建待办

**期 0（模型）**：文字链路从 `deepseek-chat` 切到 `deepseek-flash`（图片本来就是 flash）。真实 A/B（同一段社会实践通知）：两者都识别出 1 条、截止 `2026-10-19T12:00`、5 条要求、适用性 needs_confirmation；flash 的标题更完整，但**耗时 10.3s vs chat 2.2s**。3 条上游测试断言随决策更新为 flash（断言未删弱）。

**期 1（手动新建）**：
- 领域：`Source.kind` 增加 `manual`（原文必填、无图片路径），复用 text 的 mime 约束。
- 服务 `app/modules/tasks/services/manual.py`：复用确认链路的 DTO 校验与提醒解析，生成 manual 来源 + Task 后原子提交；manual 任务的 `sourceExcerpt` 取用户输入（否则会误触发「缺少可核对原文」的待确认标记）。
- 接口 `POST /api/v1/tasks`：201 返回 `{task, source}`；空标题 422、未知字段 400、提醒时刻已过 422。
- 前端：清单页头部新增「新建待办」按钮 + 原生 `<dialog>` 表单（名称/截止日期/截止时间/执行要求/提醒），保存后回到清单并刷新；样式沿用作用域化的模块样式。
- 测试：新增 `tests/tasks/test_api_manual_task.py`（7 例：创建与来源、重启持久化、空标题、未知字段、相对提醒、过去提醒、完成筛选）。`tests/tasks` **473 passed / 3 skipped**。

未提交、未推送。


## 2026-10-18：期 2 长期任务实体 + 期 6-A 日历

**期 2（后端，Goal 与 schema v2；期 3 随后升到 v3，见下节）**
- 新增 `domain/goals.py`：`Goal`（kind=plan|habit，字段互斥由 model_validator 严格约束）与 `Recurrence`。
- `storage/state_store.py` 升 schema v2：`Snapshot.goals`；**读 v1 允许（goals={}），只有写盘时才升级版本**；损坏/未知版本仍走原错误路径。迁移测试 24 例。
- `api/goals.py`：POST 201 / GET 列表（status、kind 过滤）/ GET{id} / PATCH（kind 只读）/ DELETE=归档（不删任务）。
- `GET /tasks` 增加 `from`/`to`/`goalId` 过滤（日期按 dueTime 优先、其次 startTime，含边界）。
- 连带修复：`services/reminder_runtime.py` 重建快照时保留 goals（否则开/确认提醒会丢目标）。
- `tests/tasks` 602 passed / 3 skipped（新增 129 例：54 领域 + 24 迁移 + 51 接口）。

**期 6-A（前端，日历）**
- 待办清单页新增月历：周一起始 42 格、上下月/回到今天、日期格显示任务点（>3 显示 +N）、逾期红点、今天高亮；点日期筛选列表、再点取消；「全部/未安排」切换。
- 桌面端左月历右列表两栏、≤900px 堆叠、≤640px 紧凑；全部样式作用域到 `.tasks-scope`，无内联事件/样式。
- 实测：切月、点日、未安排、今天、空日期、+N、600px 与 7 档宽度均无横向溢出，console/CSP 违规 0。

**首页口径（期 6 的一部分，Lead 实现）**
- 「今日待办」改为：今天到期 + 逾期未完成；无日期任务不上首页，改为卡片底部「另有 N 条未安排日期的待办 · 去清单安排」。
- 同步修正 `tests/browser/test_home_tasks.py` 的种子任务为"今天到期"。

全量回归 **675 passed / 3 skipped**。未提交、未推送。


## 2026-10-18：期 3/4/5（AI 规划闭环）与期 3.x 修正

- **模型**：新增 `GoalPlanningModel` 协议、`DeepSeekGoalPlanner`（deepseek-flash）与 `MockGoalPlanner`；抽出 `_post_chat_json`，让提取 / 视觉 / 规划三链路共用同一 HTTP 客户端与错误分型（503/504/502）。
- **规划服务** `services/planner.py`：缺口计算（due 优先、其次 start；跳过已有该目标任务的日期与不可用日期；60 天滚动视界）、草稿校验（plannedDate 必填、每日容量、120 条上限）、习惯实例构造、`manual` 来源构造、进度统计。
- **接口**：
  - `POST /goals/{id}/plan`：只返回草稿、不落库；无缺口不调模型；成功且有草稿才 `planRevision+1`；模型返回但全被过滤 → **502 `plan_validation_failed`**（不再伪装成"无缺口"）；响应带 `rawCount`/`dropped`。
  - `POST /goals/{id}/tasks`：批量确认落库，带 goalId/planRevision，按 draftId 幂等。
  - `POST /goals/{id}/occurrences`：习惯未来 14 天实例，按 (goalId, 自然日) 幂等，时间取 `recurrence.time` 或 20:00。
  - `GET /goals/{id}`：增加 `progress={total,completed,overdue}`。
- **计划任务补时刻**：模型只给日期时统一补 `dueTime=plannedDate 20:00 +08:00`，首页与日历归类稳定。
- **schema v3**：Task 新增 `goalId`/`occurrenceOf`/`planRevision` 后把存储版本升到 3；读取兼容 v1/v2/v3，写盘统一 v3，`.bak` 为升级前原文（字节级测试）。
- **真实 flash 验证**：15 天窗口 / 每天 2 条 → `rawCount=21 / drafts=21 / dropped=0`；两周目标 → 26 条草稿全部带日期与 20:00 截止，落库 26 条、重放幂等。
- `tests/tasks` **719 passed / 3 skipped**（新增 129 + 88 + 15 + 11 等）。

未提交、未推送。

## 2026-10-18：期 6（日历 / 长期任务 UI / AI 规划预览 / 首页口径）

- **日历**：清单页月历（周一起始 42 格、上下月/回到今天、每格任务点与 +N、逾期红点、今天高亮）；点日期筛选、再点取消；「全部日期 / 未安排」切换；桌面双栏、窄屏堆叠。
- **长期任务区**：计划/习惯卡片（进度、剩余天数、周期与时长）、新建计划/习惯对话框、目标详情抽屉（进度、元信息、关联待办可跳转、AI 规划、归档）。
- **AI 规划 UI**：点击后加载态（10–30 秒提示）→ 规划预览（可逐条移除）→「保存这些任务」落库并刷新列表/日历/进度；无缺口、503/504/502 分别给中文提示；规划结果独立于抽屉，重开不重复调模型。
- **习惯**：目标卡片/详情「生成未来 14 天」，幂等时提示 0 条。
- **首页口径**：今天到期 + 逾期未完成进入「今日待办」；无日期任务不上首页，卡片底部给「另有 N 条未安排日期的待办 · 去清单安排」。
- 修正：日历「全部」与状态筛选「全部」重名 → 改为「全部日期」。
- 全量回归 **792 passed / 3 skipped**。

未提交、未推送；生产 17843 未重启。

- **页面拆分**：「待办」拆成两个独立导航入口——`/tasks/import` 截图转待办（导入/核对）、`/tasks` 待办清单（日历/列表/长期任务）；首页「新建待办」「去导入通知」指向截图页，任务标题与「未安排」入口指向清单页。
- **修复**：首页「另有 N 条未安排日期的待办」入口因类名写死 `hidden` 实际不可见（验收 P1），改为 `hidden` 属性控制；`tests/browser/test_shell_reminders.py` 同步适配清单页默认视图。

### 最终验收后修正（期 3.4）

- `/goals/{id}/plan` 与 `/goals/{id}/occurrences` 对 archived/done 目标返回 409 `goal_not_active`：校验在模型调用与写盘之前，不消耗模型调用、不改变 revision。
- `/goals/{id}/tasks` 的 `planRevision` 改为服务端权威：忽略客户端传值，一律使用保存时目标的当前值；字段仍保留以兼容旧前端。
- 文档修正：README 回归数字从 71 更新为 792（待办 719）；期 2 的 schema v2 表述标注为当时版本，现行版本为 v3。
- `tests/tasks` **725 passed / 3 skipped**。

未提交、未推送。


## 2026-10-18：首页四块接入真实数据

- **天气**：新增 `app/modules/home`（API-only 模块，无导航路由）提供 `/api/v1/weather?city=`，服务端代理 Open-Meteo（免密钥），返回当前温度/天气/最高最低/湿度/未来 4 小时；进程内缓存 10 分钟；失败返回 503 `weather_unavailable`。
- **每日段子**：`/api/v1/daily-joke`，DeepSeek flash 生成（推理模型，`max_tokens` 需给足否则思考过程会吃光预算导致正文为空），按自然日缓存到 `<data_dir>/home/joke.json`；`?refresh=1` 强制换一条；失败 503 `joke_unavailable`。
- **随手记**：`GET/PUT /api/v1/notes` 落盘到 `<data_dir>/home/notes.json`，最多 50 行、单行 200 字。
- **日程**：暂无数据源，改为空状态（不再显示演示日程），入口指向待办清单的月历。
- 前端首页改为真实数据：天气卡支持城市切换与加载/失败态；梗词小报替换为「每日段子（AI 生成，换一条）」；随手记加载/保存走接口。
- 外壳导航跳过「可用但没有路由」的模块，避免 API-only 模块出现在侧栏。
- 新增 `tests/unit/test_home_services.py`（9 例：模块注册、天气规范化/失败、段子缓存与刷新/重启持久化/错误、随手记往返与校验、令牌边界）。
- 真实调用验证：南京 21°/阴/湿度 80%、杭州 29°/晴间多云；段子首次生成约 4.5 秒、换一条生效；随手记保存后刷新仍在。


## 2026-10-18：全局搜索接真实数据；移除「快捷导航」占位模块

- 新增 `GET /api/v1/search?q=`（home 模块）：跨项目 / 待办 / 长期任务搜索。
  - 项目来自 `ProjectService.snapshot()`（匹配名称或路径）；
  - 待办/长期任务直接读待办模块 `state.json`（标题/说明、去重、每组最多 5 条）；
  - 返回 `{query, groups:[{key,label,items:[{title,subtitle,badge,route}]}], total}`；
    空查询返回空分组，超 50 字 422，无 token 403，子系统异常时静默跳过该组。
- 首页搜索改为异步真实搜索：220ms 防抖、过期响应丢弃、搜索中/无结果/失败三态，点击结果直达 /projects 或 /tasks。
- 按用户要求删除「快捷导航」占位模块（module_registry 不再注册 navigation，侧栏不再出现「快捷导航 规划中」）。
- 测试：新增 `tests/unit/test_home_search.py`（5 例：令牌、空查询、超长、待办+长期任务、项目）；模块注册/边界/外壳测试同步更新。


## 2026-10-18：天气城市任意选择、生产部署与测试隔离

- **天气城市**：城市弹窗支持输入任意城市（后端走 Open-Meteo 地理编码），保留 4 个常用城市快捷按钮；
  切换时先乐观更新城市名，失败显示「读取失败 + 原因」，不再卡在「读取中」。
- **段子模型密钥兜底**：`joke_model` 与待办模块一致，进程环境没有 `DEEPSEEK_API_KEY` 时从 Windows
  用户环境读取，保证经快捷方式/计划任务启动的生产实例也能生成段子。
- **生产部署**：确认生产 17843 跑的是 `wb-stable`（主仓库的 linked worktree，detached 在旧提交）。
  升级流程：备份 `%LOCALAPPDATA%\PersonalWorkbench` → `git reset --hard origin/main` →
  用 uv 给 `wb-stable/.venv` 安装 requirements.lock 新增依赖（httpx 链、python-multipart）→
  重启 launcher → 冒烟（模块、天气真实、项目 6 个保留、待办库为空）。
- **测试隔离**：浏览器回归 fixture 注入 Mock 段子模型并桩掉天气请求，避免测试访问外网/调用真实模型；
  Windows 实例测试放宽等待时间（断言不变）。


## 2026-10-18：每日段子改为「世界快讯」（真实新闻 + AI 筛选）

- **原则**：不让模型凭记忆生成新闻。新闻标题与链接必须来自真实 RSS/API，模型只负责挑选与一句话解读；
  抓取失败时回退上一次成功缓存，模型失败时退回纯标题，**绝不编造**。
- 后端 `app/modules/home/news.py`：并发抓取 8 个公开 RSS（BBC 中文、中国新闻网、界面新闻、澎湃要闻、
  InfoQ、少数派、Hacker News、MIT Tech Review），RSS 2.0/Atom 命名空间兼容解析，标题去重、按时间倒序、
  最多 24 条候选；内存缓存 30 分钟并持久化到 `<data_dir>/home/news.json`。
- AI 筛选 `news_model.py`：`deepseek-flash` 从真实标题中选 5 条并写 ≤40 字解读，严格 JSON；
  索引越界/重复/解析失败一律视为无效并降级为纯标题。
- 接口 `GET /api/v1/world-news?refresh=1` → `{items, fetchedAt, aiUsed, aiError, sourceCount, totalFetched}`；
  每次刷新重抓 RSS 并重新筛选。
- 前端「世界快讯」卡片：5 条真实标题（新窗口打开原文）+ 分类标签 + 来源与时间 + AI 解读，底部注明
  「新闻来自公开 RSS，AI 只做筛选与解读」。
- 提醒会话改为 localStorage 共享：多标签页复用同一会话，避免互相 supersede 产生 409。
- 新增 `tests/unit/test_home_news.py`（8 例：RSS/Atom 解析、AI 选中、模型失败降级、非法索引、缓存复用、
  令牌边界、无源 503），浏览器 fixture 桩掉新闻抓取与模型。
- 实测：40 条来自 6 个源，AI 选出 5 条（Cloudflare 跨租户数据泄露、AI 终端落地、上合总理会议等）。


## 2026-10-18：记住天气城市

- 新增 `GET/PUT /api/v1/preferences`：把首页偏好（当前为天气城市）落盘到
  `<data_dir>/home/preferences.json`，默认南京，切换城市后自动保存；换浏览器/重启后仍在。
- 前端进入时先读服务端偏好再拉天气；localStorage 缓存一份，避免首屏先闪默认城市。
- 新增 9 个偏好测试（默认值、往返、重启持久化、非法输入、令牌边界、长度截断）。


## 2026-10-18：稳定版迁移规则与 tag 约定

- 明确目录职责：`wb` 为开发版，`wb-stable`（生产 17843）为稳定版，**开发过程中不碰 stable**。
- 每次迁移必须给实际部署的提交打 annotated tag（`v主.次.修订`），并推送 tag。
- 新增 `docs/release.md`：目录职责、铁律、迁移/回滚步骤、tag 规范、历史版本表。
- 本次已为当前部署补打 `v0.2.0`（指向 `78c9b74`）；上一稳定版为 `v0.1.0`（`1357b33`）。


## 2026-10-18：世界快讯卡片固定高度、内容内部滚动

- 卡片 `max-h-[440px]`、列表 `max-h-[300px] overflow-y-auto`：5 条常规内容正好完整显示，
  标题/解读更长时在卡片内部滚动，不再把首页撑高。
- 解读限两行（line-clamp-2）、行距收紧，保证 5 条时不出现半条裁切。
- 实测：超长内容下卡片高度 440px 不变（页面高度 0px 变化），列表 scrollHeight 356 > clientHeight 298 出现内部滚动；
  600px 宽无横向溢出。


## 2026-10-18：世界快讯按日缓存；首页第二行紧凑化

- **按日存档**：世界快讯改为每个自然日第一次进入时抓取 RSS + AI 筛选，结果写入
  `<data_dir>/home/news_briefing.json`（含 date/items/aiUsed/sourceCount）；
  当天后续进入直接读存档（实测 27–33ms），不再抓取、不再调模型；服务重启后仍读存档。
- **换一批**：仅点击「换一批」时 `refresh=1`，重新抓取并覆盖当日存档。
- **降级**：当日抓取失败时回退最近一次存档并标记 stale，前端提示「显示上次保存的新闻，今日更新失败」。
- **首页第二行紧凑化**：今日待办与世界快讯桌面端统一 380px（原 453/440），
  列表内部滚动；首页内容总高 1242px → 1053px。
- 测试更新：`tests/unit/test_home_news.py` 覆盖首次抓取、当天缓存（不抓不调模型）、
  换一批、重启后仍缓存、失败回退、AI 降级；新增 10 例。


## 2026-10-18：发布 v0.3.0 到稳定版

- 迁移流程按 `docs/release.md` 执行：备份数据 → 精确停止 `wb-stable` launcher（先子后父）→
  `git reset --hard origin/main`（`76fb7c6`）→ uv 同步依赖 → 启动 → 冒烟。
- 数据备份：`%LOCALAPPDATA%\PersonalWorkbench-backup-20261018-1755`。
- 冒烟结果：17843 health 200；模块 projects/tasks/home；项目 6 个；城市偏好（洛阳）保留；
  世界快讯首次 22.6s（生成当日存档）、再次 32ms（cached）；首页卡片 380px、总高 1053px；
  第二次进入新闻出现 199ms；待办页正常；无 console 错误。
- 已打 annotated tag `v0.3.0` 并推送，指向实际部署提交 `76fb7c6`。


## 2026-10-18：首页三块改造（常用入口 / 接下来 / 随手记）

- **常用入口**：去掉全部占位格。第一行工作台真实模块，第二行「最近项目」（按最近操作时间取前 2），
  第三行用户自定义链接（名称 + URL，最多 8 个，服务端偏好持久化）；右上角「编辑」管理自定义入口。
- **接下来**：不再空态。用真实待办生成：今天逾期/时间轴（最多 3 条）、未来 7 天负载柱状条、
  顶部「今天 X 项 · 未来 7 天 Y 项」；点任意一天跳到待办清单。
- **随手记升级为收集箱**：每条独立存储（id/文本/创建时间），支持新增、删除、**一键转成待办**、
  「查看全部」抽屉；快速输入回车即存；兼容旧的按行存储格式（读取时自动迁移）。
- 后端：`/api/v1/notes` 改为 REST（GET 列表 / POST 新增 / PUT 修改 / DELETE 删除）；
  `/api/v1/preferences` 支持 `quickEntries` 部分更新（最多 8 个、http(s) 校验、去重）。
- 布局：第三行三张卡统一 300px，内部滚动；首页 1440/600 无横向溢出。
- 测试：笔记/偏好接口测试重写并新增（19 例）；浏览器回归 21 passed；全量 **832 passed / 3 skipped**。


## 2026-10-18：数据备份与恢复

- 新增 API-only 模块 `app/modules/backup`（无导航路由）：
  - `GET /api/v1/backup/export`：导出 JSON 备份（任务/目标/来源、笔记、偏好、当日快讯、settings.toml、
    projects.toml、history），文件名 `personal-workbench-backup-YYYYMMDD-HHMMSS.json`；
  - `POST /api/v1/backup/restore`：校验格式/版本/TOML/任务快照后原子写回，**恢复前自动备份当前数据**
    到 `<data_dir>/backups/auto-*.json`（最多保留 10 份）；失败时自动回滚；
  - `GET /api/v1/backup/info`：数据目录、版本、任务/目标/来源/笔记/项目计数与自动备份列表。
- 不备份：logs/cache/esbuild/runtime、新闻抓取缓存（可重抓）、AI 密钥（系统环境变量）。
- 设置页新增「数据备份与恢复」区块：导出下载、从备份恢复（文件选择 → 预览内容 → 二次确认）、
  自动备份列表与数据目录显示；恢复成功后提示并刷新页面。
- 测试：新增 `tests/unit/test_backup.py`（6 例）；端到端验收 13/14（409 为跨浏览器提醒会话竞争）。
- 全量回归 **838 passed / 3 skipped**。


## 2026-10-18：项目识别覆盖率扩展 + 首页可编辑大字与「我的空间」

- 识别（`app/modules/projects/detectors.py`、`recipes.py`、`models.py`；新增 `tools/detection_report.py`）：
  - 检测优先级：`package.json` → `go.mod` → `Cargo.toml`+`src/main.rs` → python → 无 manifest 纯 Node → 顶层 HTML；同一目录只返回一个 Detection。
  - Python：任意顶层 `*.py` 只要有 AST main guard 即候选（不再要求 README/pyproject/main.py/app.py），排除 `test_*`、`*_test.py`、`conftest.py`、`setup.py`、符号链接、>1MiB；已知入口名（main/app/run/server/start/bot/cli/manage）优先排序，多候选仍只给 open-directory。新增 Django（顶层 `manage.py` 且可判定 Django → `manage.py runserver`）与 requirements+README 兜底（仅让项目出现、入口待选）；venv 优先 `.venv`、其次 `venv`。
  - Node：脚本优先级 dev > start > serve > preview；无脚本时依次框架推断（vite/next/nuxt/astro/svelte/angular 配置 → `npm exec …`）、`package.json main` 字段、单一入口（server.mjs/server.js/app.js/index.js/main.js）；无 package.json 时单入口兜底（有顶层 html 仍优先 web）。
  - Web：任意顶层 html 都识别；多个时优先 index.html，否则按名排序；测试/覆盖率报告类文件名（report/test/coverage/result/summary 等）不作为项目。非 index 单页生成静态 url 配方：服务端把静态 url 限制由「仅 index.html」调整为「项目目录内已存在的 .html」（resolve 后必须仍在项目根内），`01-spec.md` §5.1 已同步。
  - 新增 Go（`go.mod` 且根或 `cmd/<sub>` 下有 package main → `go run`；仅有 go.mod 的库不建项目）与 Rust（`Cargo.toml`+`src/main.rs` → `cargo run`）；项目页类型筛选增加 Go/Rust，未知类型归「其他」。
  - 扫描边界：扫描根目录若只命中弱证据（顶层 html / 无 package.json 的 Node 单入口 / 普通 Python 入口）继续下钻，避免整个根被单个文件坍缩；requirements+README 包目录仍按项目边界处理（避免展开 tests/.planning 等内部目录）。
- 首页大字可编辑：`preferences` 新增 `heroHeadline`（默认 "" 表示使用「把今天，安排清楚。」，max 30、单行）；点击标题或铅笔进入编辑，Enter/失焦保存、Esc 取消、清空保存恢复默认，失败回退；失焦保存不抢焦点，编辑框与资料编辑均忽略输入法 composition 期间的 Enter。
- 「我的空间」：`preferences` 新增 `profile{displayName 1-20, signature 0-40}`（字段级部分更新）；右上头像/移动端头像打开面板，含头像首字、资料内联编辑、今日待办/笔记/项目概览、设置与退出；Esc/点外/再点关闭，失败项显示「暂不可用」；资料编辑结束焦点回到对应按钮。
- 测试：全量 **977 passed / 4 skipped**（319.37s）；识别单测 34+9+12、偏好单测 50、浏览器用例 14；4 项跳过 = 原 3 项规则 + Windows 非开发者模式无法创建文件符号链接 1 项。compileall 通过；ruff F,E9 对本次改动文件 0 新增（仓库原有 41 项历史告警不在本次范围）。
- 说明：识别规则变化会改变既有自动项目的类型/配方（例如 Go 项目内部 panel 不再被当作独立 web 项目），首次执行新配方仍需按配方指纹确认；覆盖率样本口径与已知限制见同日验收记录。独立复核（只读）发现的弱边界、Go 无 main、报告 HTML 误报、失焦抢焦点、输入法 Enter 等问题已在提交前修复并补回归。
