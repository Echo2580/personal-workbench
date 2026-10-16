import os
import subprocess
from pathlib import Path
from .scanner import normalize_project_path, is_link
from ...core.contracts import WorkbenchError


def validate_settings(settings):
    roots = []
    for raw in settings.roots:
        p = Path(raw)
        if not p.is_absolute() or not p.is_dir() or is_link(p):
            raise WorkbenchError(
                "invalid_root", f"扫描目录不存在、不是绝对路径或是链接：{raw}", 422
            )
        try:
            with os.scandir(p):
                pass
        except OSError as e:
            raise WorkbenchError(
                "invalid_root", "扫描目录当前无法访问。", 422, str(e)
            ) from e
        normalized = normalize_project_path(p)
        if normalized not in roots:
            roots.append(normalized)
    roots = [
        r
        for r in roots
        if not any(
            r != other and Path(r).is_relative_to(Path(other)) for other in roots
        )
    ]
    if settings.default_python and not Path(settings.default_python).is_file():
        raise WorkbenchError("python_missing", "指定的 Python 文件不存在。", 422)
    return settings.model_copy(update={"roots": roots})


def validate_python(path):
    if not Path(path).is_absolute() or not Path(path).is_file():
        raise WorkbenchError(
            "python_missing", "请填写存在的 Python 解释器绝对路径。", 422
        )
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise WorkbenchError(
            "python_check_failed", "解释器验证失败。", 422, str(e)
        ) from e
    output = (result.stdout + result.stderr).strip()
    if result.returncode or not output.startswith("Python "):
        raise WorkbenchError(
            "python_check_failed", "指定程序未返回 Python 版本。", 422, output
        )
    return {"valid": True, "version": output}
