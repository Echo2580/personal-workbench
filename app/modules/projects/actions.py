import os
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit
from .windows_job import resolve_program
from ...core.contracts import WorkbenchError


class OpenActionService:
    def execute(self, recipe):
        try:
            if recipe.kind == "directory":
                if not Path(recipe.target).is_dir():
                    raise WorkbenchError("target_missing", "文件夹不存在。", 422)
                os.startfile(recipe.target)
            elif recipe.kind == "url":
                u = urlsplit(recipe.target)
                if u.scheme in ("http", "https") and u.netloc:
                    target = recipe.target
                else:
                    p = Path(recipe.target)
                    if (
                        not p.is_absolute()
                        or p.suffix.lower() != ".html"
                        or not p.is_file()
                    ):
                        raise WorkbenchError(
                            "invalid_target", "只允许已保存的网页或项目内 .html 文件。", 422
                        )
                    target = p.as_uri()
                if not webbrowser.open(target):
                    raise WorkbenchError(
                        "open_failed", "系统未能处理浏览器打开请求。", 500
                    )
            elif recipe.kind == "app":
                program = resolve_program(recipe.program)
                if Path(program).suffix.lower() in (".cmd", ".bat"):
                    # ShellExecute handles IDE launchers without putting external applications in a Job.
                    os.startfile(
                        program,
                        "open",
                        subprocess.list2cmdline(recipe.args),
                        recipe.cwd,
                    )
                else:
                    subprocess.Popen(
                        [program, *recipe.args],
                        cwd=recipe.cwd,
                        close_fds=True,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
            else:
                raise WorkbenchError("invalid_action", "此配方不是打开动作。", 422)
        except OSError as e:
            raise WorkbenchError(
                "open_failed", "打开请求失败，请检查路径或默认应用。", 422, str(e)
            ) from e
        return {
            "status": "open_requested",
            "message": "已请求打开；外部窗口不由工作台管理。",
        }
