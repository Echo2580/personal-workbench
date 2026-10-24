import os
import base64
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
import win32api
import win32con
import win32job
import win32process
from ...core.contracts import WorkbenchError


@dataclass
class JobHandle:
    job: object
    process: object
    pid: int
    closed: bool = False
    command_line: str = ""


def resolve_program(program):
    found = str(Path(program)) if Path(program).is_file() else shutil.which(program)
    if not found:
        raise WorkbenchError(
            "program_missing",
            f"找不到程序：{program}。请检查安装或编辑配方。",
            422,
            recovery_action="edit_recipe",
        )
    return str(Path(found).resolve())


def recipe_execution(recipe):
    if recipe.kind not in ("command", "script"):
        return None
    try:
        result = {"command_line": command_line(recipe)[1]}
        if batch_environment(recipe):
            result["environment"] = batch_environment(recipe)
        return result
    except WorkbenchError as e:
        return {"error": str(e)}


def powershell_source(recipe):
    if recipe.kind == "script":

        def quote(value):
            return "'" + value.replace("'", "''") + "'"

        args = [
            v
            if re.fullmatch(
                r"-[a-zA-Z_][a-zA-Z0-9_-]*(?::\$(?:true|false))?", v, re.IGNORECASE
            )
            else quote(v)
            for v in recipe.args
        ]
        return "& " + " ".join([quote(recipe.target), *args])
    return recipe.shell_command


def powershell_program():
    return str(
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )


def batch_environment(recipe):
    if recipe.kind != "script" or Path(recipe.target).suffix.lower() not in (
        ".bat",
        ".cmd",
    ):
        return {}
    return {
        "__WB_SCRIPT": recipe.target,
        **{f"__WB_ARG_{i}": value for i, value in enumerate(recipe.args)},
    }


def command_line(recipe):
    cmd = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
    if (recipe.shell_command and recipe.shell == "powershell") or (
        recipe.kind == "script" and Path(recipe.target).suffix.lower() == ".ps1"
    ):
        program = resolve_program(powershell_program())
        source = powershell_source(recipe)
        # UTF-16LE avoids Windows command-line quoting and console code-page loss.
        wrapped = (
            "& {\n"
            + source
            + "\nif (-not $?) { if ($LASTEXITCODE) { exit $LASTEXITCODE }; exit 1 }; if ($LASTEXITCODE) { exit $LASTEXITCODE }\n}"
        )
        encoded = base64.b64encode(wrapped.encode("utf-16-le")).decode("ascii")
        return program, subprocess.list2cmdline(
            [program, "-NoLogo", "-NoProfile", "-EncodedCommand", encoded]
        )
    if recipe.kind == "script":
        if Path(recipe.target).suffix.lower() == ".py":
            program = resolve_program(recipe.program)
            return program, subprocess.list2cmdline(
                [program, recipe.target, *recipe.args]
            )
        if any(
            c in value
            for value in [recipe.target, *recipe.args]
            for c in ('"', "\r", "\n")
        ):
            raise WorkbenchError(
                "batch_arguments",
                "批处理路径或参数不支持字面双引号和换行。请改用自定义 CMD 命令，按脚本约定填写完整 CMD 语法。",
                422,
                recovery_action="edit_recipe",
            )
        # Single-pass environment expansion preserves literal % and metacharacters.
        # Do not use CALL or caret escaping: both change normal batch %~1 values.
        inner = '"%__WB_SCRIPT%"' + "".join(
            ' "%__WB_ARG_' + str(i) + '%"' if value else ' ""'
            for i, value in enumerate(recipe.args)
        )
        return cmd, f'"{cmd}" /d /v:off /s /c "{inner}"'
    if recipe.shell_command:
        return cmd, f'"{cmd}" /d /s /c "{recipe.shell_command}"'
    program = resolve_program(recipe.program)
    if Path(program).suffix.lower() in (".cmd", ".bat"):
        # Auto Node commands use fixed script names; arbitrary CMD syntax belongs in shell_command.
        if any(not re.fullmatch(r"[a-zA-Z0-9_./:-]+", a) for a in recipe.args):
            raise WorkbenchError(
                "batch_arguments",
                "批处理特殊参数请改为明确的 Windows CMD 命令后确认。",
                422,
            )
        if any(c in program for c in ["%", "!", chr(34), chr(13), chr(10)]):
            raise WorkbenchError(
                "batch_path", "批处理路径包含不支持的 CMD 展开字符。", 422
            )
        inner = '"' + program + '" ' + " ".join(recipe.args)
        return cmd, f'"{cmd}" /d /s /c "{inner}"'
    return program, subprocess.list2cmdline([program, *recipe.args])


class WindowsJob:
    def start(self, recipe, cwd=None, env=None):
        cwd = cwd or recipe.cwd
        if not Path(cwd).is_dir():
            raise WorkbenchError("cwd_missing", "工作目录不存在。", 422)
        application, line = command_line(recipe)
        job = process = thread = None
        try:
            job = win32job.CreateJobObject(None, "")
            info = win32job.QueryInformationJobObject(
                job, win32job.JobObjectExtendedLimitInformation
            )
            info["BasicLimitInformation"]["LimitFlags"] = (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            win32job.SetInformationJobObject(
                job, win32job.JobObjectExtendedLimitInformation, info
            )
            win32api.SetHandleInformation(job, win32con.HANDLE_FLAG_INHERIT, 0)
            environment = dict(os.environ) if env is None else dict(env)
            environment.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
            environment.update(batch_environment(recipe))
            startup = win32process.STARTUPINFO()
            startup.lpTitle = "个人工作台 · " + recipe.label
            process, thread, pid, _ = win32process.CreateProcess(
                application,
                line,
                None,
                None,
                False,
                win32con.CREATE_SUSPENDED
                | win32con.CREATE_NEW_CONSOLE
                | win32con.CREATE_UNICODE_ENVIRONMENT,
                environment,
                str(cwd),
                startup,
            )
            win32job.AssignProcessToJobObject(job, process)
            win32process.ResumeThread(thread)
            thread.Close()
            thread = None
            return JobHandle(job, process, pid, command_line=line)
        except Exception as e:
            if process:
                try:
                    win32process.TerminateProcess(process, 1)
                finally:
                    process.Close()
            if thread:
                thread.Close()
            if job:
                job.Close()
            if isinstance(e, WorkbenchError):
                raise
            raise WorkbenchError(
                "job_start_failed",
                "无法创建受管理的独立终端；未降级为不受管理的进程。",
                500,
                str(e),
            ) from e

    def active_process_count(self, handle):
        if handle.closed:
            return 0
        return win32job.QueryInformationJobObject(
            handle.job, win32job.JobObjectBasicAccountingInformation
        )["ActiveProcesses"]

    def exit_code(self, handle):
        return win32process.GetExitCodeProcess(handle.process)

    def stop(self, handle):
        if handle.closed:
            return
        if self.active_process_count(handle):
            win32job.TerminateJobObject(handle.job, 1)
        deadline = time.monotonic() + 5
        while self.active_process_count(handle):
            if time.monotonic() > deadline:
                raise WorkbenchError(
                    "stop_timeout", "停止后进程树尚未归零，服务保持运行。", 500
                )
            time.sleep(0.02)

    def close(self, handle):
        if handle.closed:
            return
        handle.job.Close()
        handle.process.Close()
        handle.closed = True
