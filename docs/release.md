# 稳定版与发布流程

## 目录职责（重要）

| 目录 | 角色 | 谁能改 |
|---|---|---|
| `wb`（主仓库，`main` 分支） | **开发版**：所有新功能、重构、测试都在这里做 | 开发可以自由提交 |
| `wb-stable`（同一仓库的 linked worktree） | **稳定版**：用户日常运行的版本，生产端口 **17843** | **开发过程中禁止改动**；只在用户明确要求迁移时更新 |

`wb-stable` 是 `wb/.git/worktrees/wb-stable` 的链接工作树，共享同一个 Git 仓库，但工作区文件独立。
在 `wb` 上的提交**不会**自动影响 `wb-stable`；反之在 `wb-stable` 上执行 `git reset` 也不会改 `wb` 的工作区。

## 铁律

1. 开发、调试、自动化验收一律在 `wb` + 预览实例（如 17860）完成，**不要动 `wb-stable`**。
2. 需要验证"像生产一样"时，用独立数据目录启动临时实例，不要占用 17843 或改动 `wb-stable`。
3. 只有用户明确说迁移/发布，才执行下面的流程。
4. **每次迁移必须打 Git tag**（见下）。

## 迁移流程（用户确认后执行）

```powershell
$stable = 'D:\AI实训project\个人工作台\wb-stable'
$stamp  = Get-Date -Format 'yyyyMMdd-HHmm'

# 1. 备份用户数据（数据目录在 %LOCALAPPDATA%\PersonalWorkbench）
Copy-Item "$env:LOCALAPPDATA\PersonalWorkbench" "$env:LOCALAPPDATA\PersonalWorkbench-backup-$stamp" -Recurse -Force

# 2. 停止稳定版（launcher 是 pythonw -m app.launcher，父/子进程都要停）
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -like '*app.launcher*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# 3. 代码升级到 main（wb-stable 是 detached worktree，用 reset）
git -C $stable fetch origin
git -C $stable reset --hard origin/main

# 4. 依赖同步（stable 的 venv 是 uv 创建的，没有 pip）
uv pip install --python "$stable\.venv\Scripts\python.exe" -r "$stable\requirements.lock"

# 5. 启动 + 冒烟
Start-Process -FilePath "$stable\.venv\Scripts\pythonw.exe" -ArgumentList '-m','app.launcher' -WorkingDirectory $stable -WindowStyle Hidden
# 等 healthz 200，再检查 /api/v1/bootstrap 模块、天气、待办、项目数量
```

冒烟通过后：

```powershell
# 6. 给本次迁移的提交打 tag 并推送
git -C 'D:\AI实训project\个人工作台\wb' tag -a v0.2.0 <commit> -m "稳定版 v0.2.0（YYYY-MM-DD）"
git -C 'D:\AI实训project\个人工作台\wb' push origin v0.2.0
```

## Tag 规范

- 格式：`v主.次.修订`，**annotated tag**（带说明）。
- tag 指向**实际部署到 `wb-stable` 的那个提交**，不是最新 `main`。
- 说明里写清：包含的主要功能、回归数字、部署对象与端口。
- 稳定版与 `main` 之间允许有差距（`main` 上可能已有未发布的开发提交）。
- 回滚 = `git -C wb-stable reset --hard <上一个 tag 的提交>` + 重启，数据用迁移前备份。

## 已知历史

| Tag | 提交 | 说明 |
|---|---|---|
| `v0.1.0` | `1357b33` | 扫描项目 + 清单展示 + 一键启动 |
| `v0.2.0` | `78c9b74` | 并入截图转待办、重做首页与外壳、长期任务与 AI 规划、世界快讯、记住城市 |
