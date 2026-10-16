import ast
import json
import tomllib
from pathlib import Path

MAX_FILE = 1024 * 1024


def limited_read(path):
    if path.is_symlink():
        raise ValueError("不读取文件链接")
    with path.open("rb") as stream:
        content = stream.read(MAX_FILE + 1)
    if len(content) > MAX_FILE:
        raise ValueError("文件超过 1 MiB")
    return content.decode("utf-8-sig")


def main_guard(path):
    tree = ast.parse(limited_read(path))
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        t = node.test
        if (
            isinstance(t, ast.Compare)
            and len(t.ops) == 1
            and isinstance(t.ops[0], ast.Eq)
        ):
            values = [t.left, *t.comparators]
            if (
                len(values) == 2
                and any(isinstance(v, ast.Name) and v.id == "__name__" for v in values)
                and any(
                    isinstance(v, ast.Constant) and v.value == "__main__"
                    for v in values
                )
            ):
                return True
    return False


def detect_project(path, settings, warnings=None):
    from .models import Detection

    warnings = warnings if warnings is not None else []
    path = Path(path)

    def warn(e):
        warnings.append(f"{path}：{e}")

    if (path / "package.json").is_file():
        try:
            package = json.loads(limited_read(path / "package.json"))
            if not isinstance(package, dict):
                raise ValueError("package.json 顶层必须是对象")
            scripts = package.get("scripts", {})
            if not isinstance(scripts, dict):
                raise ValueError("scripts 不是对象")
            scripts = [
                s
                for s in ("dev", "start")
                if isinstance(scripts.get(s), str) and scripts[s].strip()
            ]
            manager = str(package.get("packageManager", "")).split("@")[0]
            if manager not in ("npm", "pnpm", "yarn", "bun"):
                locks = [
                    m
                    for file, m in [
                        ("package-lock.json", "npm"),
                        ("pnpm-lock.yaml", "pnpm"),
                        ("yarn.lock", "yarn"),
                        ("bun.lock", "bun"),
                        ("bun.lockb", "bun"),
                    ]
                    if (path / file).exists()
                ]
                manager = locks[0] if len(set(locks)) == 1 else "npm"
            workspaces = package.get("workspaces", [])
            if isinstance(workspaces, dict):
                workspaces = workspaces.get("packages", [])
            if not isinstance(workspaces, list):
                workspaces = []
            return Detection(
                path=str(path),
                type="node",
                scripts=scripts,
                package_manager=manager,
                workspaces=[w for w in workspaces if isinstance(w, str)],
                evidence=[
                    "package.json"
                    + (
                        "，需要配置运行脚本"
                        if not scripts
                        else " scripts: " + ", ".join(scripts)
                    )
                ],
            )
        except (OSError, ValueError, TypeError) as e:
            warn(e)
    try:
        names = list(path.iterdir())
    except OSError as e:
        warn(e)
        return None
    has_readme = any(p.name.lower().startswith("readme") and p.is_file() for p in names)
    pyproject = False
    if (path / "pyproject.toml").is_file():
        try:
            data = tomllib.loads(limited_read(path / "pyproject.toml"))
            pyproject = bool(
                data.get("project")
                or (
                    data.get("tool", {}).get("poetry")
                    if isinstance(data.get("tool", {}), dict)
                    else None
                )
            )
        except (OSError, ValueError) as e:
            warn(e)
    candidates = []
    for p in sorted(names):
        if p.suffix.lower() != ".py" or not p.is_file() or p.is_symlink():
            continue
        if (
            p.name.lower().startswith("test_")
            or p.name.lower().endswith("_test.py")
            or p.name.lower() == "conftest.py"
        ):
            continue
        if not (pyproject or has_readme or p.name in ("main.py", "app.py")):
            continue
        try:
            if main_guard(p):
                candidates.append(p.name)
        except (OSError, ValueError, SyntaxError) as e:
            warnings.append(f"{p}：{e}")
    if candidates or pyproject:
        return Detection(
            path=str(path),
            type="python",
            entry_candidates=candidates,
            evidence=["静态 main guard: " + ", ".join(candidates)]
            if candidates
            else ["pyproject 项目定义；需选择入口"],
        )
    if (path / "index.html").is_file() and not (path / "index.html").is_symlink():
        return Detection(
            path=str(path), type="web", evidence=["顶层 index.html（本地文件打开）"]
        )
    return None
