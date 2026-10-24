"""Check direct launch targets without executing project code."""

import re
from pathlib import Path

from ...core.contracts import WorkbenchError
from .windows_job import resolve_program


def validate_launch_recipe(recipe):
    if recipe.shell_command:
        return
    program = resolve_program(recipe.program)
    stem = Path(program).stem.casefold()
    python = re.fullmatch(r"python(?:w|\d+(?:\.\d+)*)?", stem)
    if not python and stem != "node":
        return
    args = list(recipe.args)
    while args and args[0].startswith("-"):
        flag = args.pop(0)
        if flag == "--":
            break
        if flag in {"-m", "-c", "-e", "-p", "--eval", "--print"}:
            return
        if flag in {"-W", "-X"}:
            if not args:
                return
            args.pop(0)
        elif flag not in {
            "-B",
            "-u",
            "-I",
            "-E",
            "-s",
            "-S",
            "-O",
            "-OO",
        } and not flag.startswith(("--inspect", "--trace-", "--no-")):
            return
    if not args or args[0] == "-":
        return
    entry = Path(args[0])
    suffixes = {".py", ".pyw"} if python else {".js", ".mjs", ".cjs"}
    if entry.suffix.casefold() not in suffixes:
        return
    target = entry if entry.is_absolute() else Path(recipe.cwd) / entry
    if not target.is_file():
        raise WorkbenchError(
            "entry_missing",
            f"启动脚本不存在：{target}。请检查项目根目录和配方中的入口文件。",
            422,
            {"entry": str(target), "cwd": recipe.cwd},
            recovery_action="edit_recipe",
        )
