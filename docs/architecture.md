# 架构与扩展

## 运行结构

`start.cmd → scripts/start.ps1 → .venv/pythonw -m app.launcher`。入口按 Windows 用户及数据目录建立命名互斥体，通过令牌和实例 ID 验证现有服务；新服务先占住可用 socket，再运行单 worker Uvicorn。HTTP 验证就绪后打开首页，生产不使用 reload。

`app/main.py` 是组装层：创建公共服务、项目模块及公开路由，提供静态网页、同源 bootstrap 和系统入口。公共数据/安全/关停契约在 `app/core/`；扫描、配方、运行状态均在 `app/modules/projects/`。

## 模块接口

`ModuleDefinition` 提供 id、title、description、icon、route、status、router、summary_provider、settings_route。`ModuleRegistry.register()` 拒绝重复 ID 与可用路由。首页和侧栏从同一份 bootstrap 模块目录生成，规划中模块不具有业务路由。

前端 `core/module-loaders.js` 只登记公开入口；模块的 `mountPage(container, context)` 和可选 `mountSettings()` 接收 API、导航、反馈、AbortSignal 等通用上下文，返回 cleanup。路由切换会中止请求并清理轮询和抽屉。首页只读 metrics/recent_links/availability，不读取项目模型。

新模块接入步骤：

1. 创建独立后端目录并公开 `ModuleDefinition`，在 `module_registry.py` / 组装层登记；`create_app(..., extra_modules=...)` 也支持显式组合。
2. 创建独立前端目录，导出 mountPage 和可选 mountSettings，在 loader map 挂接。
3. 提供通用摘要。需要后台任务时，在组装层将其 running_items、stop_all、block_actions 接到通用关停协调器。
4. 为模块添加测试。不要修改 projects 内部文件来接入新模块。

临时笔记模块的后端路由、前端导航、首页、独立页和设置挂接已由测试验证，测试模块不会进入产品注册表。关停核心通过回调工作，不读取项目 PID、配方或状态字段。网页退出预览使用 `/api/v1/system/shutdown-preview` 的通用 running_items。

## 项目数据流

设置与人工覆盖的 TOML 是事实来源；扫描 JSON 是缓存。`ProjectService` 合并自动项目、手动目录和完整人工覆盖，保留历史与活跃运行临时卡片。扫描在单独工作线程执行，同时只允许一轮，后台调度在完成后等待配置周期。

识别只读顶层标识和有界文件，读取上限 1 MiB。Python 用 AST 判断 main guard，不 import；测试运行器不作为业务入口。Node 用 scripts 和包管理器信息生成原生命令。识别优先级为 package.json → go.mod → Cargo.toml → Python → 无 manifest 纯 Node → 顶层 HTML；扫描根目录若只命中弱证据（html/单入口/requirements）会继续下钻，普通已识别项目内仍不拆子项目，显式 workspaces 才继续检查独立子目录。Go/Rust 配方分别使用 `go`、`cargo` 原生命令。

路径规范化后用 SHA-256 完整摘要建立 ID。名称不是身份，PID 不是管理授权。配方指纹包括项目身份、类型、程序、参数、工作目录和目标；批准接口仅保存当前指纹，执行接口再次校验。

TOML 以内容摘要作 revision，PUT/DELETE 要求 If-Match；写入同目录临时文件、fsync 后替换，保存上一有效版本。外部语法或字段错误被报告，已存在 Job 的停止路由不依赖损坏配方解析。测试使用独立临时数据目录。

## Windows 进程与打开动作

`windows_job.py` 封装 pywin32：创建 KILL_ON_JOB_CLOSE Job → CREATE_SUSPENDED + CREATE_NEW_CONSOLE 创建进程 → 分配 Job → ResumeThread。失败时清理挂起进程与句柄，不能降级为不受管理进程。Job 句柄不继承。

`runtime.py` 管理每项目单命令、状态锁、500ms 真实 Job 活动进程检查、入口退出码和历史。入口退出但子进程仍在，仍显示运行；Job 归零后结束。停止用 TerminateJobObject 并等待归零，是强制终止，不承诺项目自行执行优雅回调。入口退出码不等于所有后代业务成功。

Node 的 .cmd shim 使用固定 cmd.exe 包装；自动脚本参数为 dev/start。特殊批处理参数需明确改用 CMD 命令并重新确认。cwd 始终单独传递，测试覆盖中文、空格和 `&`。应用、目录、网页由 `actions.py` 打开，不放进项目 Job，也不通过名称查杀程序。

服务异常退出后操作系统关闭 Job 句柄；新实例只把旧未结束历史记为 interrupted，不复用历史 PID。运行快照不嵌套旧运行，避免历史递归膨胀。

## 边界与验证

只绑定 loopback，同源提供页面和 API；校验 Host、Origin、会话令牌，不开放 CORS。用户内容使用文本节点；固定 CSP 禁止跨站脚本及 frame 嵌入。业务输入 DTO 拒绝多余字段，命令执行只能引用已保存项目/配方和当前指纹。

测试以真实 Windows Job、独立控制台键盘事件、真实 npm 子进程及完整浏览器请求验证关键边界；故障系统调用通过窄范围注入覆盖。mock 不替代父子进程、终端交互或真实状态测试。扫描与真实项目运行分开验收。

系统行为参考：[Microsoft 进程创建标志](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)、[Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)。实际行为以本机集成证据为准。


## 项目移除与恢复（2026-10-16）

`projects.toml.removed_projects` 使用规范化路径的项目 ID 为键，保存 path、name、removed_at；旧配置没有该表时按空表兼容。记录持久保留，扫描缓存不能覆盖它。移除不清除 manual_projects、overrides、history 或 approvals，恢复只解除该项目的隐藏标记并请求扫描，不扩大扫描范围；若目录已移动或不在当前扫描范围且没有手动登记，恢复并不承诺找回磁盘项目。

项目快照在合并运行状态后过滤已移除项目，因此首页统计、最近使用与项目页一致。若外部手工编辑配置将活跃项目标为隐藏，仍保留其临时卡片，确保停止入口可达。服务锁内检查活跃状态并写配置，避免启动与移除竞争；被移除项目无法通过旧卡片 ID 执行或批准配方。再次手动添加已移除路径返回 project_removed，提示在设置恢复。

API：GET `/api/v1/projects/removed` 返回 projects 和 revision；DELETE `/api/v1/projects/{id}`、POST `/api/v1/projects/{id}/restore` 均要求 If-Match。项目列表增加 revision，确认框固定使用打开时的版本，后台轮询不会改变本次确认依据。写入继续使用原子替换、备份与内容版本校验。旧 DELETE `/{id}/manual` 仅保留兼容用途，当前 UI 统一使用项目移除接口。

前端兼容仍加载旧后端的更新窗口：新移除能力不可用时提示正常退出再启动，设置页仍可使用；不会自动重启服务或中止当前运行。


## 2026-10-16 单实例就绪恢复

Windows 命名互斥体仍是实例所有权依据。runtime/instance.json 仅作为快速定位缓存，读取失败或握手无效时，重复入口在指定候选端口与原10秒截止时间内查找服务。通过 bootstrap 获取候选会话，然后用受令牌保护的 instance 和 system/about 交叉校验实例 ID 与规范化数据目录，其他数据目录即使令牌、ID有效也不接受。恢复入口不改写现有实例文件、不按历史 PID 查杀、不停止项目。HTTP 探测忽略系统代理、禁止重定向，响应限制64KiB，不将会话令牌写日志。

冷启动以当前进程创建的端口、令牌、实例 ID直接验证自身 HTTP 就绪，避免启动过程中元数据文件丢失而将已就绪服务自行退出。目录在入口规范化为绝对路径。互斥体持有者确实没有可验证服务时仍报告超时，保留排错信息，不强制夺取所有权。


## 2026-10-16 自定义显示名称

projects.toml 增加可选 project_names 表，以项目ID为键保存 path/name。项目身份与配方仍由原路径/配方内容确定，改名不会影响指纹、批准记录和进程。旧配置缺少该表时按空表读取；名称输入去首尾空白、1–120字符、拒绝换行和控制字符，错误配置继续遵循最后有效快照和修复提示。

PATCH `/api/v1/projects/{id}/name` 接收 `{name}`，DELETE 同一路径恢复默认，两者要求 If-Match，服务锁内原子写入。默认名称为自动项目目录名或手动登记时的名称；单独别名不会将自动项目变为手动登记，也不会改变 recipe_source。项目快照增加 default_name、has_custom_name，并声明 capabilities.project_names，以便仍加载旧后端的页面给出正常重启提示。

名称在扫描、手动项目、活跃运行合并后覆盖显示，因此临时运行卡片同样可改名；恢复默认仍使用保存的默认名称。退出预览使用当前别名，历史运行快照保持原样，不重写审计历史。首页与搜索/排序沿用同一项目快照，移除列表也优先显示名称元数据。移除项目不会清除别名。名称输入对话框固定使用打开时的revision，后台轮询不会更新其确认依据，冲突时保留草稿。
