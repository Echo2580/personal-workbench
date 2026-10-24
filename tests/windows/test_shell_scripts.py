import json
import os
import subprocess
import sys
import time

import psutil
import pytest

from app.modules.projects.models import Recipe
from app.modules.projects.windows_job import (
    WindowsJob,
    command_line,
    powershell_program,
)


def wait_for(check):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.05)
    assert check(), "临时脚本执行超时"


def execute(recipe, env=None):
    job = WindowsJob()
    handle = job.start(recipe, env=env)
    try:
        wait_for(lambda: job.active_process_count(handle) == 0)
        return job.exit_code(handle)
    finally:
        job.stop(handle)
        job.close(handle)


@pytest.mark.parametrize("suffix", [".py", ".cmd", ".bat", ".ps1"])
def test_script_unicode_spaces_quotes_and_arguments(tmp_path, suffix):
    root = tmp_path / "中文 空格 & 目录"
    root.mkdir()
    output = root / "result.json"
    dump = root / "参数.py"
    dump.write_text(
        "import json,sys,pathlib\npathlib.Path('result.json').write_text(json.dumps(sys.argv[1:],ensure_ascii=False),encoding='utf-8')\n",
        encoding="utf-8",
    )
    target = root / ("启动 ' 脚本" + suffix)
    if suffix == ".py":
        target.write_text(dump.read_text(encoding="utf-8"), encoding="utf-8")
    elif suffix == ".ps1":
        target.write_text(
            "[IO.File]::WriteAllText('result.json', (ConvertTo-Json -InputObject @($args) -Compress))",
            encoding="utf-8-sig",
        )
        policy = subprocess.check_output(
            [powershell_program(), "-NoProfile", "-Command", "Get-ExecutionPolicy"],
            text=True,
        ).strip()
        if policy in {"Restricted", "AllSigned"}:
            pytest.skip(f"本机 {policy} 不允许运行未签名临时 .ps1；不更改策略")
    else:
        target.write_text(
            f'@echo off\r\nchcp 65001>nul\r\n"{sys.executable}" "{dump}" %*\r\nexit /b %errorlevel%\r\n',
            encoding="utf-8",
        )
    args = ["中文 参数", "a&b", "x|y", "100%PATH%", "wow!", "", "it's"]
    if suffix in (".py", ".ps1"):
        args += ['a"b& c', "last\\"]
    recipe = Recipe(
        id="r",
        label="临时测试",
        kind="script",
        cwd=str(root),
        target=str(target),
        program=sys.executable if suffix == ".py" else None,
        args=args,
    )
    assert execute(recipe) == 0, command_line(recipe)
    assert json.loads(output.read_text(encoding="utf-8")) == args


@pytest.mark.parametrize("suffix", [".bat", ".cmd"])
def test_batch_normal_parameter_expansion_and_rejected_quotes(tmp_path, suffix):
    script = tmp_path / ("literal" + suffix)
    args = [
        "中文 参数",
        "a&b",
        "x|y",
        "100%PATH%",
        "wow!",
        "last\\",
        "",
        "^()<>;",
        "it's",
    ]
    dump = tmp_path / "dump.py"
    dump.write_text(
        "import json,os,pathlib;pathlib.Path('result.json').write_text(json.dumps([os.environ.get('ARG'+str(i),'') for i in range(9)]),encoding='utf-8')",
        encoding="utf-8",
    )
    source = (
        "@echo off\nchcp 65001>nul\n"
        + "".join(f'set "ARG{i}=%~1"\nshift\n' for i in range(len(args)))
        + f'"{sys.executable}" "{dump}"\n'
    )
    script.write_text(source, encoding="utf-8")
    recipe = Recipe(
        id="r",
        label="真实批处理参数",
        kind="script",
        cwd=str(tmp_path),
        target=str(script),
        args=args,
    )
    assert execute(recipe) == 0
    assert json.loads((tmp_path / "result.json").read_text()) == args
    from app.core.contracts import WorkbenchError

    for unsupported in ['a"b', "line\nbreak"]:
        with pytest.raises(WorkbenchError, match="双引号"):
            command_line(recipe.model_copy(update={"args": [unsupported]}))


def test_powershell_named_parameters(tmp_path):
    target = tmp_path / "named.ps1"
    target.write_text(
        "param([string]$Name,[switch]$Flag)\n[IO.File]::WriteAllText('named.txt', $Name + ':' + $Flag)",
        encoding="utf-8-sig",
    )
    recipe = Recipe(
        id="r",
        label="命名参数",
        kind="script",
        cwd=str(tmp_path),
        target=str(target),
        args=["-Name", '中文 a"b', "-Flag"],
    )
    assert execute(recipe) == 0
    assert (tmp_path / "named.txt").read_text(encoding="utf-8-sig") == '中文 a"b:True'


@pytest.mark.parametrize(
    "shell,source,code",
    [
        ("cmd", "exit /b 7", 7),
        ("powershell", "exit 9", 9),
        ("powershell", "throw '失败'", 1),
        ("powershell", "& $env:COMSPEC /d /c 'exit 13'", 13),
    ],
)
def test_shell_failure_exit_codes(tmp_path, shell, source, code):
    recipe = Recipe(
        id="r",
        label="临时测试",
        kind="command",
        cwd=str(tmp_path),
        shell=shell,
        shell_command=source,
    )
    assert execute(recipe) == code


def test_powershell_variables_pipeline_multiline_and_policy_failure(tmp_path):
    recipe = Recipe(
        id="r",
        label="临时测试",
        kind="command",
        cwd=str(tmp_path),
        shell="powershell",
        shell_command="$x = '中文 空格'\n$x | ForEach-Object { [IO.File]::WriteAllText('result.txt', $_) }",
    )
    assert execute(recipe) == 0
    assert (tmp_path / "result.txt").read_text(encoding="utf-8-sig") == "中文 空格"
    script = tmp_path / "blocked.ps1"
    script.write_text(
        "[IO.File]::WriteAllText('never.txt','bad')", encoding="utf-8-sig"
    )
    blocked = Recipe(
        id="r", label="策略拒绝", kind="script", cwd=str(tmp_path), target=str(script)
    )
    env = dict(os.environ, PSExecutionPolicyPreference="Restricted")
    assert "ExecutionPolicy" not in command_line(blocked)[1]
    assert execute(blocked, env) != 0
    assert not (tmp_path / "never.txt").exists()


def test_powershell_job_stops_child_process_tree(tmp_path):
    script = tmp_path / "child.py"
    script.write_text(
        "import subprocess,sys,pathlib,time\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\npathlib.Path('child.pid').write_text(str(p.pid))\ntime.sleep(60)",
        encoding="utf-8",
    )
    source = f"& '{sys.executable}' '{script}'"
    recipe = Recipe(
        id="r",
        label="临时进程树",
        kind="command",
        cwd=str(tmp_path),
        shell="powershell",
        shell_command=source,
    )
    job = WindowsJob()
    handle = job.start(recipe)
    try:
        wait_for(lambda: (tmp_path / "child.pid").exists())
        pid = int((tmp_path / "child.pid").read_text())
        assert psutil.pid_exists(pid)
        job.stop(handle)
        wait_for(lambda: not psutil.pid_exists(pid))
        assert job.active_process_count(handle) == 0
    finally:
        job.stop(handle)
        job.close(handle)
