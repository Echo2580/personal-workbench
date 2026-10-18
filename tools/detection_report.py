"""只读识别基准脚本：扫描本机工作台数据目录的 roots，输出自动识别与配方结果。

默认不写文件、不启动服务、不读取运行缓存；只读 settings.toml 与项目目录标识文件。
用法：
  .\\.venv\\Scripts\\python.exe tools\\detection_report.py
  .\\.venv\\Scripts\\python.exe tools\\detection_report.py --data-dir D:\\tmp\\data --json
  .\\.venv\\Scripts\\python.exe tools\\detection_report.py --roots "D:\\AI实训project\\llm" "D:\\other"
"""

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
# 只读基准：导入项目代码时不在仓库生成 .pyc。
sys.dont_write_bytecode = True

from app.modules.projects.models import ProjectSettings  # noqa: E402
from app.modules.projects.scanner import scan_roots  # noqa: E402


def default_data_dir():
    override = os.environ.get("WORKBENCH_DATA_DIR")
    if override:
        return Path(override)
    return REPO_ROOT / "data"


def load_raw_settings(data_dir):
    path = Path(data_dir) / "settings.toml"
    if not path.is_file():
        return {}, path
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    if not isinstance(data, dict):
        raise SystemExit(f"配置文件格式不正确：{path}")
    return data, path


def build_settings(data_dir, roots_override):
    raw, path = load_raw_settings(data_dir)
    if roots_override:
        roots = [str(Path(item).expanduser()) for item in roots_override]
    else:
        if not path.is_file():
            raise SystemExit(f"找不到配置文件：{path}；可用 --roots 指定扫描目录。")
        roots = raw.get("roots", [])
        if not isinstance(roots, list) or not all(isinstance(x, str) for x in roots):
            raise SystemExit(f"配置文件 roots 字段格式不正确：{path}")
        roots = [str(Path(item).expanduser()) for item in roots]
    allowed = set(ProjectSettings.model_fields)
    filtered = {key: value for key, value in raw.items() if key in allowed}
    filtered["roots"] = roots
    try:
        return ProjectSettings.model_validate(filtered)
    except ValueError:
        # 扫描选项损坏时仍只输出 roots 的只读报告，不修复、不写盘。
        return ProjectSettings(roots=roots)


def quote_arg(value):
    text = str(value)
    return '"' + text + '"' if (not text or any(c in text for c in " \t")) else text


def display_recipe(recipe):
    if recipe.shell_command:
        return recipe.shell_command
    if recipe.program:
        return " ".join(quote_arg(item) for item in [recipe.program, *recipe.args])
    return recipe.target or ""


def recipe_payload(recipe):
    return {
        "id": recipe.id,
        "label": recipe.label,
        "kind": recipe.kind,
        "cwd": recipe.cwd,
        "program": recipe.program,
        "args": list(recipe.args),
        "shell_command": recipe.shell_command,
        "target": recipe.target,
        "display": display_recipe(recipe),
    }


def project_payload(project):
    primary = next(
        (recipe for recipe in project.recipes if recipe.id == project.primary_recipe_id),
        None,
    )
    return {
        "name": project.name,
        "path": project.path,
        "type": project.type,
        "evidence": list(project.evidence),
        "primary_recipe_id": project.primary_recipe_id,
        "primary": recipe_payload(primary) if primary else None,
        "has_primary_command": bool(primary and primary.kind == "command"),
        "recipes": [recipe_payload(recipe) for recipe in project.recipes],
    }


def collect(data_dir, roots_override):
    settings = build_settings(data_dir, roots_override)
    result = scan_roots(settings, [])
    counts = {}
    for project in result.projects:
        counts[project.type] = counts.get(project.type, 0) + 1
    projects = [project_payload(project) for project in result.projects]
    return {
        "data_dir": str(Path(data_dir)),
        "roots": list(settings.roots),
        "root_states": dict(result.root_states),
        "limited": result.limited,
        "warnings": list(result.warnings),
        "project_count": len(projects),
        "primary_command_count": sum(
            1 for project in projects if project["has_primary_command"]
        ),
        "type_counts": dict(sorted(counts.items())),
        "projects": projects,
    }


def print_text(payload):
    print("项目识别基线（只读；不写文件、不启动服务、不读运行缓存）")
    print(f"数据目录：{payload['data_dir']}")
    print(f"扫描根目录：{len(payload['roots'])} 个")
    for root in payload["roots"]:
        state = payload["root_states"].get(root, "unknown")
        print(f"  - {root} [{state}]")
    counts = " · ".join(
        f"{name} {count}" for name, count in payload["type_counts"].items()
    )
    print(
        f"发现项目：{payload['project_count']} 个；limited={str(payload['limited']).lower()}；"
        f"主配方为命令：{payload['primary_command_count']} 个"
    )
    print(f"类型统计：{counts or '无'}")
    for index, project in enumerate(payload["projects"], start=1):
        print()
        print(f"[{index}] {project['name']}  ({project['type']})")
        print(f"    路径：{project['path']}")
        evidence = "；".join(project["evidence"]) or "无"
        print(f"    证据：{evidence}")
        primary = project["primary"]
        if primary:
            print(f"    主配方：{primary['id']} · {primary['label']} · {primary['display']}")
        for recipe in project["recipes"]:
            print(
                f"      - {recipe['id']} [{recipe['kind']}] {recipe['label']}：{recipe['display']}"
            )
    if payload["warnings"]:
        print()
        print("警告：")
        for warning in payload["warnings"]:
            print(f"  - {warning}")


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass
    parser = argparse.ArgumentParser(
        description="只读输出本机项目自动识别与配方生成结果，用于 before/after 基线对比。"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="工作台数据目录（默认 <项目根>\\data；只读）。",
    )
    parser.add_argument(
        "--roots",
        nargs="+",
        default=None,
        help="覆盖扫描根目录（可多个）；不读取 settings.toml 里的 roots。",
    )
    parser.add_argument(
        "--json", action="store_true", help="输出 JSON，便于 before/after 机器对比。"
    )
    args = parser.parse_args(argv)
    data_dir = (args.data_dir or default_data_dir()).resolve()
    payload = collect(data_dir, args.roots)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_text(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
