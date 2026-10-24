"""Bounded, read-only script discovery; never evaluate project files."""

import os
from pathlib import Path

from ...core.contracts import WorkbenchError
from .models import ProjectSettings
from .scanner import is_link

SCRIPT_SUFFIXES = {".bat", ".cmd", ".ps1", ".py"}
SCRIPT_DIRECTORIES = {"scripts", "bin", "tools"}


def validate_script_path(project_path, target):
    root = Path(project_path)
    path = Path(target)
    if not path.is_absolute():
        path = root / path
    try:
        relative = path.resolve().relative_to(root.resolve())
        excluded = {s.casefold() for s in ProjectSettings().excluded_names}
        if any(part.casefold() in excluded for part in relative.parts):
            raise ValueError("环境或依赖目录")
        current = path
        while current != root and current != current.parent:
            if is_link(current):
                raise ValueError("链接")
            current = current.parent
        if (
            is_link(root)
            or path.suffix.lower() not in SCRIPT_SUFFIXES
            or not path.is_file()
        ):
            raise ValueError("文件不存在或类型不支持")
    except (OSError, ValueError) as e:
        raise WorkbenchError(
            "invalid_script",
            "脚本必须是项目内已有的 .bat/.cmd/.ps1/.py 文件，且不能位于链接、环境或依赖目录。",
            422,
            {"script": str(path)},
            recovery_action="edit_recipe",
        ) from e
    return path.resolve()


def discover_scripts(project_path, settings):
    root = Path(project_path)
    candidates, warnings = [], []
    budget, limited = 400, False
    excluded = {
        n.casefold()
        for n in [*ProjectSettings().excluded_names, *settings.excluded_names]
    }
    pending = [(root, 0)]
    while pending:
        path, depth = pending.pop(0)
        try:
            if is_link(path):
                continue
            with os.scandir(path) as entries:
                for entry in entries:
                    if budget == 0 or len(candidates) >= 100:
                        limited = True
                        break
                    budget -= 1
                    child = Path(entry.path)
                    if entry.name.casefold() in excluded or is_link(child):
                        continue
                    if (
                        entry.is_file(follow_symlinks=False)
                        and child.suffix.lower() in SCRIPT_SUFFIXES
                    ):
                        candidates.append(str(child.relative_to(root)))
                    elif (
                        depth == 0
                        and entry.name.casefold() in SCRIPT_DIRECTORIES
                        and entry.is_dir(follow_symlinks=False)
                    ):
                        pending.append((child, 1))
        except OSError:
            warnings.append(f"无法读取：{path}")
        if limited:
            break
    return {
        "candidates": sorted(candidates, key=str.casefold),
        "limited": limited,
        "warnings": warnings,
    }
