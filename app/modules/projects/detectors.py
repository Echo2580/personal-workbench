import ast
import json
import re
import tomllib
from pathlib import Path

MAX_FILE = 1024 * 1024

# 已知入口名优先排序，其余按文件名排序；多候选仍需人工选择。
PYTHON_ENTRY_PRIORITY = (
    "main.py",
    "app.py",
    "run.py",
    "server.py",
    "start.py",
    "bot.py",
    "cli.py",
    "manage.py",
)
PYTHON_IGNORED = ("setup.py", "conftest.py")

# 测试/覆盖率报告类 HTML 不作为静态站点自动建档（避免误报）。
REPORT_HTML = re.compile(
    r"(^|[-_.])(report|reports|test|tests|coverage|result|results|summary)([-_.]|$)",
    re.IGNORECASE,
)

NODE_SCRIPT_ORDER = ("dev", "start", "serve", "preview")
NODE_ENTRY_FILES = (
    "server.mjs",
    "server.js",
    "server.cjs",
    "app.js",
    "index.js",
    "main.js",
)
# (框架, 配置前缀, 允许后缀, 推断命令, 展示名)
NODE_FRAMEWORKS = (
    ("next", "next.config", (".js", ".mjs", ".cjs", ".ts", ".mts"), ("next", "dev"), "Next"),
    ("nuxt", "nuxt.config", (".js", ".mjs", ".cjs", ".ts"), ("nuxt", "dev"), "Nuxt"),
    ("astro", "astro.config", (".js", ".mjs", ".cjs", ".ts"), ("astro", "dev"), "Astro"),
    ("svelte", "svelte.config", (".js", ".mjs", ".cjs", ".ts"), ("vite",), "Svelte"),
    ("angular", "angular.json", (), ("ng", "serve"), "Angular"),
    ("vite", "vite.config", (".js", ".mjs", ".cjs", ".ts", ".mts", ".cts"), ("vite",), "Vite"),
)
PACKAGE_MANAGERS = ("npm", "pnpm", "yarn", "bun")
PACKAGE_LOCKS = (
    ("package-lock.json", "npm"),
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("bun.lock", "bun"),
    ("bun.lockb", "bun"),
)

PACKAGE_MAIN = re.compile(r"(?m)^\s*package\s+main\b")


def limited_read(path):
    if path.is_symlink():
        raise ValueError("不读取文件链接")
    with path.open("rb") as stream:
        content = stream.read(MAX_FILE + 1)
    if len(content) > MAX_FILE:
        raise ValueError("文件超过 1 MiB")
    return content.decode("utf-8-sig")


def plain_file(path):
    """普通文件：存在、非符号链接。"""
    return path.is_file() and not path.is_symlink()


def plain_dir(path):
    """普通目录：存在、非符号链接/junction。"""
    return path.is_dir() and not (path.is_symlink() or path.is_junction())


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


def node_framework_args(manager, command):
    """框架推断命令在不同包管理器下的等价写法。"""
    if manager in ("pnpm", "yarn"):
        return ["exec", *command]
    if manager == "bun":
        return ["x", *command]
    return ["exec", "--", *command]


def _main_guard_candidates(names, warn):
    candidates = []
    for item in names:
        if item.suffix.casefold() != ".py" or not plain_file(item):
            continue
        name = item.name.casefold()
        if name.startswith("test_") or name.endswith("_test.py"):
            continue
        if name in PYTHON_IGNORED:
            continue
        try:
            if main_guard(item):
                candidates.append(item.name)
        except (OSError, ValueError, SyntaxError) as e:
            warn(e)
    order = {name: index for index, name in enumerate(PYTHON_ENTRY_PRIORITY)}
    candidates.sort(key=lambda name: (order.get(name.casefold(), len(order)), name.casefold()))
    return candidates


def _has_settings_module(names):
    for item in names:
        if item.name.casefold() == "settings.py" and plain_file(item):
            return True
        if plain_dir(item) and plain_file(item / "settings.py"):
            return True
    return False


def _django_project(path, names, warn):
    manage = path / "manage.py"
    if not plain_file(manage):
        return False
    try:
        if "django" in limited_read(manage).casefold():
            return True
    except (OSError, ValueError) as e:
        warn(e)
    return _has_settings_module(names)


def _node_framework(names):
    for framework, prefix, suffixes, command, label in NODE_FRAMEWORKS:
        for item in names:
            if not plain_file(item):
                continue
            low = item.name.casefold()
            matched = (
                low == prefix
                if not suffixes
                else low.startswith(prefix) and low[len(prefix):] in suffixes
            )
            if matched:
                return framework, item.name, command, label
    return None


def _node_main_entry(path, package):
    main = package.get("main")
    if not isinstance(main, str) or not main.strip():
        return ""
    relative = Path(main.strip())
    if relative.is_absolute() or ".." in relative.parts:
        return ""
    if not plain_file(path / relative):
        return ""
    return main.strip()


def _node_single_entry(names):
    wanted = {name.casefold() for name in NODE_ENTRY_FILES}
    found = [
        item.name
        for item in names
        if plain_file(item) and item.name.casefold() in wanted
    ]
    return found[0] if len(found) == 1 else ""


def _detect_node(path, names, warn):
    from .models import Detection

    manifest = path / "package.json"
    if not plain_file(manifest):
        return None
    try:
        package = json.loads(limited_read(manifest))
        if not isinstance(package, dict):
            raise ValueError("package.json 顶层必须是对象")
        raw_scripts = package.get("scripts", {})
        if not isinstance(raw_scripts, dict):
            raise ValueError("scripts 不是对象")
        scripts = [
            name
            for name in NODE_SCRIPT_ORDER
            if isinstance(raw_scripts.get(name), str) and raw_scripts[name].strip()
        ]
        manager = str(package.get("packageManager", "")).split("@")[0]
        if manager not in PACKAGE_MANAGERS:
            locks = [m for file, m in PACKAGE_LOCKS if (path / file).exists()]
            manager = locks[0] if len(set(locks)) == 1 else "npm"
        workspaces = package.get("workspaces", [])
        if isinstance(workspaces, dict):
            workspaces = workspaces.get("packages", [])
        if not isinstance(workspaces, list):
            workspaces = []
        evidence = []
        entry = ""
        framework = ""
        if scripts:
            evidence.append("package.json scripts: " + ", ".join(scripts))
        else:
            inferred = _node_framework(names)
            if inferred:
                framework, config, command, _label = inferred
                args = node_framework_args(manager, command)
                evidence.append(
                    f"package.json（无运行脚本）；框架推断：{config} → {manager} {' '.join(args)}"
                )
            else:
                entry = _node_main_entry(path, package)
                if entry:
                    evidence.append(
                        f"package.json（无运行脚本）；main 字段：{entry} → node {entry}"
                    )
                else:
                    entry = _node_single_entry(names)
                    if entry:
                        evidence.append(
                            f"package.json（无运行脚本）；顶层入口文件：{entry} → node {entry}"
                        )
            if not framework and not entry:
                evidence.append("package.json，需要配置运行脚本")
        return Detection(
            path=str(path),
            type="node",
            scripts=scripts,
            package_manager=manager,
            workspaces=[w for w in workspaces if isinstance(w, str)],
            entry_candidates=[entry] if entry else [],
            framework=framework,
            evidence=evidence,
        )
    except (OSError, ValueError, TypeError) as e:
        warn(e)
        return None


def _package_main_go(file, warn):
    try:
        return PACKAGE_MAIN.search(limited_read(file)) is not None
    except (OSError, ValueError) as e:
        warn(e)
        return False


def _sorted_children(root):
    return sorted(
        (item for item in root.iterdir() if plain_dir(item)),
        key=lambda item: (item.name.casefold(), item.name),
    )


def _detect_go(path, names, warn):
    from .models import Detection

    if not plain_file(path / "go.mod"):
        return None
    for item in names:
        if item.suffix.casefold() != ".go" or not plain_file(item):
            continue
        if _package_main_go(item, warn):
            return Detection(
                path=str(path),
                type="go",
                entry_candidates=["."],
                evidence=[f"go.mod；package main：{item.name}"],
            )
    cmd = path / "cmd"
    subdirs = []
    if plain_dir(cmd):
        try:
            subdirs = _sorted_children(cmd)
        except OSError as e:
            warn(e)
        for subdir in subdirs:
            try:
                files = sorted(
                    (
                        item
                        for item in subdir.iterdir()
                        if item.suffix.casefold() == ".go" and plain_file(item)
                    ),
                    key=lambda item: (item.name.casefold(), item.name),
                )
            except OSError as e:
                warn(e)
                continue
            for item in files:
                if _package_main_go(item, warn):
                    relative = f"./cmd/{subdir.name}"
                    return Detection(
                        path=str(path),
                        type="go",
                        entry_candidates=[relative],
                        evidence=[
                            f"go.mod；cmd 入口：cmd/{subdir.name}/{item.name}（package main）"
                        ],
                    )
    # 没有 package main 的 go.mod 多为库，不作为可启动项目（保持保守口径）。
    return None


def _detect_rust(path):
    from .models import Detection

    if not plain_file(path / "Cargo.toml"):
        return None
    src = path / "src"
    if not plain_dir(src) or not plain_file(src / "main.rs"):
        return None
    return Detection(
        path=str(path), type="rust", evidence=["Cargo.toml；src/main.rs"]
    )


def _detect_python(path, names, warn):
    from .models import Detection

    if _django_project(path, names, warn):
        return Detection(
            path=str(path),
            type="python",
            entry_candidates=["manage.py"],
            framework="django",
            evidence=["manage.py（Django 项目）"],
        )
    candidates = _main_guard_candidates(names, warn)
    if candidates:
        return Detection(
            path=str(path),
            type="python",
            entry_candidates=candidates,
            evidence=["静态 main guard: " + ", ".join(candidates)],
        )
    pyproject = False
    if plain_file(path / "pyproject.toml"):
        try:
            data = tomllib.loads(limited_read(path / "pyproject.toml"))
            tool = data.get("tool", {})
            pyproject = bool(
                data.get("project")
                or (tool.get("poetry") if isinstance(tool, dict) else None)
            )
        except (OSError, ValueError) as e:
            warn(e)
    if pyproject:
        return Detection(
            path=str(path), type="python", evidence=["pyproject 项目定义；需选择入口"]
        )
    has_readme = any(
        item.name.casefold().startswith("readme") and plain_file(item)
        for item in names
    )
    requirements = next(
        (
            name
            for name in ("requirements.txt", "requirements-dev.txt")
            if plain_file(path / name)
        ),
        "",
    )
    if requirements and has_readme:
        return Detection(
            path=str(path),
            type="python",
            evidence=[f"{requirements}；需选择或配置入口"],
        )
    return None


def _detect_pure_node(path, names):
    from .models import Detection

    if (path / "package.json").exists():
        return None
    if any(plain_file(item) and item.suffix.casefold() == ".html" for item in names):
        return None
    entry = _node_single_entry(names)
    if not entry:
        return None
    return Detection(
        path=str(path),
        type="node",
        entry_candidates=[entry],
        evidence=[f"顶层入口文件 {entry}（无 package.json）"],
    )


def _detect_web(path, names):
    from .models import Detection

    htmls = sorted(
        (
            item
            for item in names
            if item.suffix.casefold() == ".html"
            and plain_file(item)
            and not REPORT_HTML.search(item.stem)
        ),
        key=lambda item: (item.name.casefold(), item.name),
    )
    if not htmls:
        return None
    index = next(
        (item for item in htmls if item.name.casefold() == "index.html"), None
    )
    chosen = index or htmls[0]
    if index is not None:
        evidence = (
            ["顶层 index.html（本地文件打开）"]
            if len(htmls) == 1
            else [f"顶层有 {len(htmls)} 个 HTML，优先 index.html（本地文件打开）"]
        )
    elif len(htmls) == 1:
        evidence = [f"顶层 HTML：{chosen.name}（本地文件打开）"]
    else:
        evidence = [
            f"顶层有 {len(htmls)} 个 HTML，按名称选择 {chosen.name}（本地文件打开）"
        ]
    return Detection(
        path=str(path), type="web", entry_candidates=[chosen.name], evidence=evidence
    )


def detect_project(path, settings, warnings=None):
    warnings = warnings if warnings is not None else []
    path = Path(path)

    def warn(e):
        warnings.append(f"{path}：{e}")

    try:
        names = sorted(
            path.iterdir(), key=lambda item: (item.name.casefold(), item.name)
        )
    except OSError as e:
        warn(e)
        return None

    detection = _detect_node(path, names, warn)
    if detection:
        return detection
    detection = _detect_go(path, names, warn)
    if detection:
        return detection
    detection = _detect_rust(path)
    if detection:
        return detection
    detection = _detect_python(path, names, warn)
    if detection:
        return detection
    detection = _detect_pure_node(path, names)
    if detection:
        return detection
    return _detect_web(path, names)
