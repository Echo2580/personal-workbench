# 个人工作台 Windows 首版 · 详细实施计划

> 给执行者：先读 `01-产品与UI规格.md` 与 `03-新会话执行指令.md`。用户选择单线推进，采用本人在当前会话逐项实施的方式；适用时使用 superpowers:executing-plans。所有产品行为以规格为准。收到用户发送的实施指令后才修改正式项目，不能把本文件自身当作授权。

**Goal：** 完成可双击使用的个人工作台公共外壳与完整项目启动器，保留后续功能位置。

**Architecture：** Python 单进程本地服务提供 API 与静态网页；公共外壳与项目模块分开。项目模块维护扫描、配方和 Windows Job 生命周期。前端使用原生 ES Modules，通过统一模块目录与 loader map 挂接功能。

**Tech Stack：** Python 3.12+、FastAPI、Uvicorn、tomlkit、pywin32；HTML/CSS/JavaScript；pytest、Python Playwright。

**Spec：** 同目录 `01-产品与UI规格.md`，含本次全部产品确认与 UI 设计。

## 全局约束

- 正式仓库为 `D:\AI实训project\个人工作台\wb`。交接包目录位于相邻 gpt 中，不能把实现写进交接包。
- 本次用户已批准 GUI 目录设置、配方编辑、进程跟踪与停止；同步修订旧文档相反表述。
- Windows；安装 Python 和依赖后双击；独立交互终端；仅管理本工作台启动的 command。
- 默认进入工作台首页，公共导航预留快捷导航、待办与日历；规划中模块无假功能。
- 原生前端、同源服务、单 worker。前端不增加运行时 Node 或远程 CDN 依赖。
- 只读扫描 `D:\AI实训project\llm`。测试和应用使用不能擅自修改其现有项目代码、数据库、密钥或环境。
- 专用环境属于工作台；不能在共享项目环境中安装工作台依赖。
- 实际配置与历史在用户数据目录；测试通过 WORKBENCH_DATA_DIR 指向测试临时目录，不能污染个人配置。
- AI 不执行 commit/push；完成后提供用途明确的 PowerShell 命令和 commit message 建议。
- 原型截图仅供参考。最终 UI 以规格为准；生产页面只能展示真实运行数据。

## Review Focus

1. 狼人杀与 Todo CLI 的 stdin 必须可交互；不能只证明进程能创建。由任务 4 的真实控制台验证和任务 8 的验收覆盖。
2. npm/watcher 子进程及根进程先退出场景必须正确停止；同名外部进程不受影响。由任务 4 的 Job 真实集成测试覆盖。
3. 后台扫描不能覆盖人工配方；外部修改与抽屉草稿冲突不能丢数据。由任务 3 与任务 5 的保存冲突测试覆盖。
4. 隐藏缓存、coverage HTML 和子目录不能被误识别；独立前后端必须分别展示。由任务 2 的混合目录测试覆盖。
5. 重复双击、端口被其他程序占用、浏览器关闭和服务异常退出必须保持约定行为。由任务 7 的独立进程测试覆盖。

## 开始前：核对基线与执行环境

- [ ] 确认目标目录存在，读取适用 AGENTS.md，读取最新 README、分析文档与本地交接说明。
- [ ] 在真实仓库核对 Git 状态、分支、远端和已有代码。若已出现实现，先与本方案做差异分析，保留用户已有修改。
- [ ] 如果 Git 命令因路径或权限失败，先解决该问题；不声称工作树干净，不重新初始化仓库。
- [ ] 将规格与计划复制到正式仓库的 `docs/` 作为实施依据；在 devlog 记录本次修订 GUI 与进程管理范围的用户确认。
- [ ] 检测 Python 版本、pywin32 可用性、默认浏览器；明确真实项目依赖尚未验证。
- [ ] 为依赖选用当前可安装且兼容的稳定版本，安装后冻结锁文件，记录版本。这里不凭记忆写一个未经安装验证的版本号。
- [ ] 在任务 1 测试之前先创建工作台专用 .venv 并安装开发依赖；任务 7 再把已验证流程固化为 setup.ps1。安装前检测解释器，不依赖一个尚未实现的 setup 脚本。

建议基线命令，均由执行者在明确实施授权下运行；不含提交：

```powershell
Set-Location -LiteralPath 'D:\AI实训project\个人工作台\wb'
git status --short --branch
git remote -v
git log -5 --oneline
py -0p
```

## 公开 DTO 与类型归属

项目 DTO 定义在 `app/modules/projects/models.py`，通用模块/错误类型定义在 `app/core/contracts.py`；不由多个文件各定义一套同名结构。

- `RecipeSet`：recipes、primary_recipe_id。`RecipeDocument` 再含 project_id、source、revision，各配方的 fingerprint 随读取结果提供。
- `ProjectSettings`：roots、default_python、scan_interval_seconds、max_depth、max_directories、excluded_names；默认值与规格一致。
- `SettingsDocument`：settings、revision。`RecipeOverride`：path、recipes、primary_recipe_id。
- `Detection`：path、type、entry_candidates、package_manager、evidence。`DetectedProject`：身份字段＋自动 RecipeSet＋发现时间。
- `ScanResult`：scan_id、projects、root_states、warnings、started_at、completed_at、limited。`ProjectSnapshot`：合并后的 projects、最近 ScanResult、is_scanning。
- `NativeCommand`：program、args。`ShellCommand`：shell_command；不可同时提供两种执行方式。`CommandRecipe` 与 `OpenRecipe` 为 Recipe 的受约束联合类型。
- `JobHandle` 只含管理器持有的系统句柄及入口进程信息，不可 JSON 序列化到历史。
- `StopAllResult`：stopped（run_id 列表）、failed（run_id、错误码、错误说明列表）。
- `ModuleSummary`：metrics（label/value 项）、recent_links（label、route、params 项）、availability。首页不依赖 projects 结构。
- `Run` 与状态机按规格；所有 API 时间使用 UTC ISO 8601，path、ID、fingerprint 的字段命名保持一致。

## 任务 1：基础服务、文件保存与公共模块契约

**交付：** 可启动的本地服务、统一错误响应、隔离的配置读写和模块目录。尚无业务项目时页面和 API 正确返回空状态。

**文件：**

- 创建 `pyproject.toml`、`requirements.lock`、`requirements-dev.lock`。
- 创建 `app/__init__.py`、`app/main.py`、`app/module_registry.py`。
- 创建 `app/core/contracts.py`、`config_files.py`、`security.py`。
- 创建 `app/modules/projects/module.py` 作为模块公开定义；初期 router/summary 可以未初始化，任务 3 与 6 接入真实能力。
- 测试 `tests/unit/test_config_files.py`、`test_module_registry.py`、`tests/integration/test_api_boundary.py`。

**接口：**

- `create_app(data_dir: Path | None = None) -> FastAPI`。
- `resolve_data_dir(override: Path | None = None) -> Path`：默认 LocalAppData，测试显式覆盖。
- `read_toml(path: Path) -> ConfigDocument`；`ConfigDocument` 包含 parsed、text、revision。
- `write_toml_atomic(path: Path, document: TOMLDocument, expected_revision: str) -> str`：冲突抛 ConfigConflict，不部分写入。
- `ModuleDefinition` 使用规格字段；`module_registry.list_modules() -> list[ModuleDefinition]`。
- `create_session_token() -> str`；API middleware 检查 token、Host、Origin。

**步骤：**

- [ ] 先写文件保存测试：中文路径读写；保留无关配置；模拟写入失败后原文件完整；revision 变化导致冲突。
- [ ] 先写 API 边界测试：无令牌/错误令牌 POST 403；外部 Host/Origin 403；正常同源令牌通过；healthz 不泄漏配置。
- [ ] 运行测试，确认失败来自缺少目标实现，再实现最小配置与服务骨架。
- [ ] 建立统一 Pydantic 响应，业务请求拒绝多余字段；生产静态资源仅从 app/web 读取。
- [ ] 模块目录先登记 projects 可用、navigation/tasks 规划中；尚未实现的 summary 明确返回未初始化而不是虚构数量。
- [ ] 运行并记录：

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\unit\test_config_files.py tests\unit\test_module_registry.py tests\integration\test_api_boundary.py -q
```

**通过：** 上述场景全部通过，任何无权限请求不能触发配置或执行副作用。

## 任务 2：扫描、识别、人工目录与自动配方

**交付：** 对临时混合项目库产生正确清单；对真实根目录只读扫描，形成识别报告。

**文件：** `app/modules/projects/{models,settings,scanner,detectors,recipes,store}.py`；`tests/unit/test_scanner.py`、`test_detectors.py`、`test_recipe_generation.py`、`tests/integration/test_discovery.py`、`tests/fixtures/`。

**接口：**

- `normalize_project_path(path: Path) -> str`，`project_id(path: Path) -> str`。
- `scan_roots(settings: ProjectSettings, manual_paths: list[Path]) -> ScanResult`。
- `detect_project(path: Path, settings: ProjectSettings) -> Detection | None`。
- `generate_recipes(detection: Detection, settings: ProjectSettings) -> RecipeSet`。
- `merge_project(auto: DetectedProject | None, manual: ManualProject | None, override: RecipeOverride | None) -> Project`。
- `ProjectStore.load_snapshot() -> ProjectSnapshot`、`replace_scan(result: ScanResult) -> ProjectSnapshot`。

**步骤：**

- [ ] 构建小型临时树：Node dev/start、Python main.py、非标准 todo.py main guard、多个入口、静态 index.html、requirements-only、coverage HTML、章节练习和嵌套前后端。
- [ ] 测试应得到的目录集合，断言排除 coverage/缓存/章节，前后端各一项，werewolf 风格项目不把 persona 再建成项目。
- [ ] 测试重叠根目录、大小写路径、同名不同目录、无权限目录、根目录暂时不可用，以及预算/深度警告。
- [ ] Windows 专用测试建立 junction，确认不跟随；无权限创建时明确记录 skip 原因，不把它当通过。
- [ ] 先跑测试确认失败，再用 os.scandir、AST 和 JSON 静态解析实现；禁止 import 或执行目标代码。
- [ ] 加入单扫描协调器；同时触发只产生一个 scan_id，完成后 15 秒才开始下一轮。
- [ ] 让一轮失败保留有效旧快照，输出根目录状态；正常扫描删除旧发现项目时保留配置历史与活跃运行所需条目。
- [ ] 对 `D:\AI实训project\llm` 只读运行一次扫描，输出候选路径、类型、主配方、识别理由及待补环境；人工核对，不把章节个数当项目个数。
- [ ] 记录真实识别与样本限制，不能凭“找到了 main.py”认定运行成功。

验证：`python -m pytest tests/unit/test_scanner.py tests/unit/test_detectors.py tests/unit/test_recipe_generation.py tests/integration/test_discovery.py -q`，其中 python 必须使用工作台专用环境。

**通过：** 混合目录的预期集合完全一致；无自动执行目标代码；真实扫描报告可供逐条验收。

## 任务 3：配方覆盖、配置 API 与保存语义

**交付：** 用户可保存多个配方、选择主配方，扫描不会覆盖人工结果；冲突和恢复有明确行为。

**文件：** `recipes.py`、`settings.py`、`store.py`、`service.py`、`router.py`；`tests/unit/test_recipe_overrides.py`、`test_settings.py`、`tests/integration/test_recipe_api.py`。

**接口：**

- `ProjectService.get_recipes(project_id: str) -> RecipeDocument`。
- `save_recipes(project_id: str, draft: RecipeSet, expected_revision: str) -> RecipeDocument`。
- `reset_override(project_id: str, expected_revision: str) -> RecipeDocument`。
- `save_settings(draft: ProjectSettings, expected_revision: str) -> SettingsDocument`。
- `add_manual_project(path: Path, name: str | None) -> Project`。
- `recipe_fingerprint(project_id: str, recipe: Recipe) -> str`；批准记录保存为 `history/approvals.json`。

**步骤：**

- [ ] 测试完整人工覆盖在重扫后保持；一个项目恢复自动不会清空其他项目覆盖；手动目录仍保留。
- [ ] 测试不合法字段组合、0 条配方、主配方缺失/不存在、被修改的内容指纹、危险 URL scheme 均失败。
- [ ] 测试两个编辑者的旧 revision 保存返回 409，原文件与新配置不丢失。
- [ ] 测试直接手改 TOML 后读取刷新；语法损坏返回可修复错误，保留已有运行的停止能力。
- [ ] 写 API 并接服务；请求验证、文件锁与 per-project 操作锁顺序一致，避免死锁。
- [ ] 支持设置默认解释器；验证接口用短超时 `--version`，不用 import 项目测试环境。
- [ ] 测试“运行中配方不能修改”的规则；其他打开类配方可保存。API 不能只靠 UI 禁用来实现约束。
- [ ] 保存成功触发重算或受控重扫，缓存不反向覆盖配置。

验证：`python -m pytest tests/unit/test_recipe_overrides.py tests/unit/test_settings.py tests/integration/test_recipe_api.py -q`。

**通过：** 配置可来回编辑，错误和并发均不会静默丢失用户内容。

## 任务 4：独立终端与 Windows Job 管理

**交付：** 支持真实启动、状态、停止命令树，且不影响外部程序。

**文件：** `windows_job.py`、`runtime.py`、`actions.py`；`tests/unit/test_runtime.py`、`tests/windows/test_job_lifecycle.py`、`test_console_interaction.py`；临时测试脚本仅在 tests/fixtures 内。

**接口：**

- `WindowsJob.start(command: NativeCommand | ShellCommand, cwd: Path, env: dict[str,str]) -> JobHandle`。
- `WindowsJob.active_process_count(handle: JobHandle) -> int`。
- `WindowsJob.stop(handle: JobHandle) -> None`；`close(handle: JobHandle) -> None`。
- `RuntimeManager.launch(project: Project, recipe: CommandRecipe) -> Run`。
- `RuntimeManager.stop(run_id: str) -> Run`；`list_runs() -> list[Run]`。
- `RuntimeManager.active_count() -> int`；`stop_all() -> StopAllResult`。
- `OpenActionService.execute(recipe: OpenRecipe) -> OpenResult`。

**步骤：**

- [ ] 用可控离线脚本定义真实测试：等待 stdin 后回显、长时间运行、启动子进程后父退出、非 0 退出、立即正常退出。
- [ ] 将 Job 系统调用封装在单一适配层；失败测试覆盖 CreateProcess、Assign、Resume 任一步失败均关闭句柄与挂起进程。
- [ ] 实现 suspended → assign Job → resume，CREATE_NEW_CONSOLE，Job 句柄不可继承，KILL_ON_JOB_CLOSE。
- [ ] 实现每项目互斥与重复请求保护；并发两个 launch 只创建一个 Job，另一请求返回现有运行冲突。
- [ ] 真实集成测试：停止父子树后活动进程为 0；测试外部同名对照进程仍活着；父先退出、子仍在时状态仍 running。
- [ ] 测试 stop_requested 优先于入口强制退出码，将用户停止显示 stopped，不错误显示异常退出。
- [ ] 测试快速结束脚本不会被错误标记为运行中；非 0 显示 failed，保留入口退出码。
- [ ] 真实控制台验证键盘输入；不能用 stdin=PIPE 的后台脚本冒充独立终端。记录可复现操作证据。
- [ ] 测试打开网页/目录/IDE 不创建 Job，也不改变当前命令状态；URL/目标验证失败不打开。
- [ ] 测试历史不会在新服务实例接管旧 PID；服务异常退出由 Job 清理其子树。

验证：`python -m pytest tests/unit/test_runtime.py tests/windows -q`。系统集成测试必须在 Windows 执行；执行结束检查 fixture 进程已清理。

**通过：** 真实父子进程停止与外部对照隔离成立；stdin 交互可用；不能只凭 mock 测试宣布通过。

## 任务 5：项目页、配方抽屉与设置页

**交付：** 按 UI 规格使用真实 API 完成启动器操作；不嵌入演示数据。

**文件：**

- `app/web/core/{api,dom,notifications}.js`。
- 创建最小 `app/web/index.html`、`shell.js`、`core/router.js` 与 `styles/tokens.css`，提供项目/设置页面测试入口；任务 6 完善首页、公共导航与模块化，不重复创建一套外壳。
- `app/web/modules/projects/{index,api,page,card,recipe-editor,settings}.js`、`styles.css`。
- `tests/browser/test_projects.py`、`test_recipe_editor.py`、`test_project_settings.py`。

**接口：**

- `api.request(path, {method, body, signal, revision}) -> Promise<ResponseData>`，集中添加 token、处理错误和 revision。
- `mount(container, context) -> cleanup`；project module 导出 `mountPage`、`mountSettings`。
- `renderProjectCard(project, callbacks) -> HTMLElement`。
- `openRecipeEditor(projectId, context) -> Promise<EditorResult>`，使用可访问 dialog 与右侧布局。

**步骤：**

- [ ] 写浏览器用例：无目录引导、真实空列表、搜索/筛选/排序、名称与路径复制、同名不同路径显示。
- [ ] 用测试专用离线项目和临时数据目录启动完整 API；项目页读取其真实响应，不在生产代码写 fixture 分支。
- [ ] 按规格实现双列独立高度卡片、配方展开、主动作和停止；只展开一张卡片。
- [ ] 首次/改动后的配方确认需展示命令与 cwd，完成批准 API 后调用执行；旧指纹失败时重新取当前配方，不静默执行新内容。
- [ ] 实现抽屉字段、添加/删除、主配方唯一性、取消/未保存提醒、保存冲突保留草稿、恢复自动识别确认。
- [ ] 实现扫描目录设置与默认解释器；添加项目单独检查是否存在，不把浏览器目录上传控件当本机完整路径选择器。
- [ ] 真实运行状态用轮询更新，按规格区分打开与运行；路由离开清理计时器与请求。
- [ ] 测试服务断连后禁用危险操作、恢复后刷新真实状态；测试项目名含 HTML 标记时只显示文本。
- [ ] 测试运行中编辑限制与停止后解锁；终端退出变化反映到页面。
- [ ] 样式按 tokens.css，离线 SVG；表单错误、hover、focus、disabled、loading、error、empty 完整覆盖。

验证：`python -m pytest tests/browser/test_projects.py tests/browser/test_recipe_editor.py tests/browser/test_project_settings.py -q`。Playwright 使用实际安装的受支持浏览器；缺失依赖需安装，不能跳过后宣称 UI 完成。

**通过：** 完整设置→发现→编辑→确认→启动→停止链路可操作，错误有恢复动作，无生产 mock 数据。

## 任务 6：工作台首页、公共导航与模块接入

**交付：** 用户默认进入工作台，能看出当前与未来模块，公共外壳不被项目结构绑死。

**文件：** 完善任务 5 的 `app/web/index.html`、`shell.js`、`core/router.js`、`styles/tokens.css`；创建 `core/module-loaders.js`、`pages/home.js`、`pages/settings.js`、`styles/shell.css`；完善 `app/modules/projects/module.py`；测试 `tests/integration/test_module_extension.py`、`tests/browser/test_workbench_shell.py`。

**接口：**

- `register_module(definition: ModuleDefinition) -> None`：组装时注册，拒绝重复 ID 与重复可用路由。
- `summary_provider() -> ModuleSummary`：通用 metrics 列表＋最多 4 条 recent_links，不暴露项目内部模型给公共核心。
- `navigate(route, params?)`；hash 路由 `#/`、`#/projects`、`#/settings`。
- `moduleLoaders[moduleId] -> Promise<ModuleFrontend>`：只登记公开入口，不深层导入其他模块内部。

**步骤：**

- [ ] 写测试确认默认首页、前进后退、刷新恢复当前页、未知路由的恢复入口。
- [ ] 从同一模块目录生成首页入口与侧栏；projects 可用，navigation/tasks 规划中且不进入业务路由。
- [ ] 首页摘要用真实扫描与运行数据；最近项目只链接定位项目页，复用已有启动流程。
- [ ] 设置页按模块公开挂接组织，公共设置不直接读取 projects.toml。
- [ ] 做一个仅在测试上下文登记的假模块，验证路由、菜单、首页和设置接入；比较 projects 文件内容不变，测试模块不进入发布注册表。
- [ ] 验证跨页面清理资源，重复切换不增加轮询数量；全局断连提示与项目页反馈一致。
- [ ] 对 1440×900、1280×800、1024×768 一次性截图，检查路径溢出、卡片高度、侧栏、抽屉与键盘焦点；窄窗口再检查导航可达。
- [ ] 根据第一轮发现集中修复，最多再做一轮确认；不要无休止换色和微调。

验证：`python -m pytest tests/integration/test_module_extension.py tests/browser/test_workbench_shell.py -q`。

**通过：** 新模块无需改 projects 内部，首页与导航一致，视觉与交互符合独立工作台定位。

## 任务 7：安装、双击入口、单实例与退出

**交付：** 用户首次安装后，通过一个入口稳定启动与退出。

**文件：** `app/launcher.py`、`app/core/{instance,shutdown}.py`、`scripts/setup.ps1`、`scripts/start.ps1`、`start.cmd`；`tests/windows/test_instance.py`、`test_shutdown.py`、`tests/integration/test_launcher.py`。

**接口：**

- `acquire_instance_mutex() -> InstanceOwnership`。
- `find_existing_instance(data_dir: Path) -> VerifiedInstance | None`。
- `start_or_open(data_dir: Path) -> LaunchResult`：存在则打开；不存在则启动，最多 10 秒等待。
- `ShutdownCoordinator.request(confirmed_stop_running: bool) -> ShutdownResult`。

**步骤：**

- [ ] 测试双入口并发只产生一个服务；启动未完成时另一入口等待就绪，不另起实例。
- [ ] 测试默认端口被无关 HTTP 程序占用时顺延；错误实例身份或旧 token 不能被复用。
- [ ] 测试 stale instance.json 可恢复；所有候选端口占用时清晰失败并释放互斥体。
- [ ] 实现安装与日常入口，PowerShell 使用 LiteralPath 和参数数组，处理中文空格路径；后台服务隐藏窗口，目标命令窗口按规格显示。
- [ ] setup 只修改工作台专用环境；锁定依赖文件可复现安装；不修改全局执行策略，不悄悄安装 Node。
- [ ] 测试关闭浏览器服务和命令继续；再次双击恢复首页与运行状态。
- [ ] 测试退出有运行任务返回确认列表；取消无影响；确认后全部停止再退出；停止失败保留服务。
- [ ] 测试终止测试服务进程后 Job 树退出；新服务不会拿历史 PID 查杀其他程序。
- [ ] 当前电脑手动双击 start.cmd 验证，不用“python -m uvicorn 能跑”代替入口验收。

验证：`python -m pytest tests/windows/test_instance.py tests/windows/test_shutdown.py tests/integration/test_launcher.py -q`。

**通过：** 正常使用无手动起服务与输入 URL；重复入口、冲突与退出行为全部有证据。

## 任务 8：真实接入、全量验证与交付记录

**交付：** 本机可用首版、真实验收记录与后续使用清单。

**文件：** 更新 `README.md`、`docs/JTBD与Pre-mortem分析.md`；创建/更新 `docs/architecture.md`、`docs/devlog.md`、`docs/acceptance.md`；完善 `.gitignore`。

**步骤：**

- [ ] 在本机私有设置中接入 `D:\AI实训project\llm`；扫描不写目标项目代码或配置。
- [ ] 检查 README 指定共享解释器是否存在；存在也不等于其全部依赖可用。给周测 4 的运行配方明确解释器；狼人杀参数按 README 和用户实际选择展示。
- [ ] 对代表项目逐条记录检测、配方、环境与真实启动结果；缺失 MySQL、密钥或外部服务时记录具体阻碍，不猜凭据，不记 PASS。
- [ ] 真实项目首次运行通过用户在工作台确认配方与点击执行完成；有外部调用/业务数据副作用的项目只记录实际发生的验证，不能由测试夹具冒充。
- [ ] 使用临时可控项目完成父子进程停止、交互输入、快速退出、异常退出与自动发现的自动化验收。
- [ ] 创建 100 项目临时样本记录扫描耗时；实际目录识别率单独统计，未建立真实项目分母时标记未测。
- [ ] 运行全量检查并保存输出摘要：

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\unit tests\integration tests\windows tests\browser -q
& .\.venv\Scripts\python.exe -m compileall app
```

- [ ] 全量测试通过后，只有出现新修改、失败或新问题才重跑相关检查；不要反复无意义全量测试。
- [ ] 将 GUI 与进程跟踪的本次修订同步进 README 与基线，不静默保留互相矛盾的开工边界。
- [ ] 交付安装步骤、start.cmd 入口、本地数据位置、已测与待测清单、已知限制及截图。
- [ ] 给出 commit message 建议及用途明确的 PowerShell git 命令，由发起人自行执行；检查暂存建议不包含个人路径配置、API key、用户历史或其他已有未跟踪文件。
- [ ] 将组员 ≤30 分钟接入、两周使用与 80% 真实识别率未完成部分明确留在验收表，不标成“全部完成”。

## 实施期暂停与询问规则

以下情况应带证据询问用户：需要改变工作台定位、合并前后端自动编排、改为网页终端、接管外部程序、放弃 Windows Job 而改变停止保证、缺失运行信息无法从现有文档/环境确认、遇到会覆盖用户已有实现的冲突。

其余工程细节按本规格执行。已经明确授权的范围不要重复询问；工具权限审批仍按运行环境要求处理，不能绕过。

## 自检对照

| 规格 | 任务 |
|---|---|
| 工作台首页、统一导航、模块预留 | 1、6 |
| 扫描、自动发现、真实项目组织 | 2 |
| 配方、多主从关系、人工覆盖 | 2、3、5 |
| GUI 目录设置与配方编辑 | 3、5 |
| 独立终端、运行状态、停止 | 4、5 |
| 本地 API 边界、同源令牌 | 1、3、5 |
| 数据持久化、冲突、恢复 | 1、3 |
| 安装、双击、单实例、退出 | 7 |
| Windows 真实运行与视觉验收 | 4、6、7、8 |
| 文档同步、真实指标、长期验收 | 8 |

任务间公开接口以本文件和规格中的名称为准；执行者若调整命名，必须同步全部消费者与文档，不能留两套相似接口。
