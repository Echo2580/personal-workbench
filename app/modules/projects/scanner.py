import hashlib
import os
from pathlib import Path
from uuid import uuid4
from .models import ScanResult, DetectedProject, utcnow
from .detectors import detect_project
from .recipes import generate_recipes

STRONG_MARKERS = ("package.json", "go.mod", "Cargo.toml", "pyproject.toml", "manage.py")


def has_strong_marker(path):
    """目录根部是否有强项目清单文件；弱命中（仅 html/单入口/requirements 等）不算。"""
    return any((Path(path) / name).is_file() for name in STRONG_MARKERS)


def root_boundary_is_weak(path, detection):
    """扫描根目录的命中是否属于「单文件式弱证据」，弱证据不能作为扫描边界。

    requirements 依赖清单 + README 的包目录仍按项目边界处理（避免展开其 tests/、
    .planning/ 等内部目录）；纯 html / 无 package.json 的 Node / 普通 Python 入口
    视为弱证据，允许继续下钻找子项目。
    """
    if has_strong_marker(path):
        return False
    if detection.type == "python" and any(
        (Path(path) / name).is_file()
        for name in ("requirements.txt", "requirements-dev.txt")
    ):
        return False
    return True


def normalize_project_path(path):
    return os.path.normcase(os.path.abspath(os.path.normpath(str(path))))


def project_id(path):
    return hashlib.sha256(normalize_project_path(path).encode("utf-8")).hexdigest()


def is_link(path):
    return path.is_symlink() or path.is_junction()


def scan_roots(settings, manual_paths, scan_id=None):
    start = utcnow()
    projects = {}
    warnings = []
    states = {}
    visited = set()
    count = 0
    limited = False
    excluded = {n.casefold() for n in settings.excluded_names}

    def visit(path, depth):
        nonlocal count, limited
        key = normalize_project_path(path)
        if key in visited:
            return
        if count >= settings.max_directories:
            limited = True
            if "扫描达到目录数量预算" not in warnings:
                warnings.append("扫描达到目录数量预算")
            return
        try:
            if is_link(path):
                return
            visited.add(key)
            count += 1
            detection = detect_project(path, settings, warnings)
            if detection:
                recipe_set = generate_recipes(detection, settings)
                projects[key] = DetectedProject(
                    id=project_id(path),
                    name=path.name,
                    path=str(path),
                    type=detection.type,
                    recipes=recipe_set.recipes,
                    primary_recipe_id=recipe_set.primary_recipe_id,
                    evidence=detection.evidence,
                )
                # Only explicitly declared, local workspace directories escape the project boundary.
                for pattern in detection.workspaces:
                    if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
                        warnings.append(f"{path}：忽略非本地工作区 {pattern}")
                        continue
                    for child in path.glob(pattern):
                        if child.is_dir() and child != path and not is_link(child):
                            relative = child.relative_to(path)
                            if any(
                                part.casefold() in excluded for part in relative.parts
                            ):
                                continue
                            if depth + len(relative.parts) <= settings.max_depth:
                                visit(child, depth + len(relative.parts))
                            else:
                                limited = True
                                warnings.append(f"{child}：工作区超过深度限制")
                # 扫描根目录若只命中弱证据（html/单入口等），继续下钻，
                # 避免整个扫描根被单个文件坍缩成一个项目而吞掉子项目。
                if depth > 0 or not root_boundary_is_weak(path, detection):
                    return
            with os.scandir(path) as it:
                children = sorted(
                    [
                        Path(e.path)
                        for e in it
                        if e.name.casefold() not in excluded
                        and e.is_dir(follow_symlinks=False)
                    ],
                    key=lambda p: p.name.casefold(),
                )
            if depth >= settings.max_depth:
                if children:
                    limited = True
                    warnings.append(f"{path}：已达到深度限制")
                return
            for child in children:
                visit(child, depth + 1)
        except OSError as e:
            warnings.append(f"{path}：{e}")

    roots = []
    for raw in settings.roots:
        path = Path(os.path.abspath(raw))
        key = normalize_project_path(path)
        if key not in {normalize_project_path(p) for p in roots}:
            roots.append(path)
        try:
            if not path.is_dir() or is_link(path):
                raise OSError("目录不存在、不可访问或是链接，请填写实际目录")
            with os.scandir(path):
                pass
            states[raw] = "available"
        except OSError as e:
            states[raw] = "root_unavailable"
            warnings.append(f"{raw}：{e}")
    for root in sorted(roots, key=lambda p: len(p.parts)):
        original = next(
            (
                raw
                for raw in settings.roots
                if normalize_project_path(raw) == normalize_project_path(root)
            ),
            str(root),
        )
        if states.get(original) == "available":
            visit(root, 0)
    for raw in manual_paths:
        path = Path(os.path.abspath(raw))
        key = normalize_project_path(path)
        if key in projects:
            projects[key].manual = True
            continue
        detection = (
            detect_project(path, settings, warnings)
            if path.is_dir() and not is_link(path)
            else None
        )
        if detection:
            rs = generate_recipes(detection, settings)
            typ = detection.type
        else:
            from .models import Recipe, RecipeSet

            rs = RecipeSet(
                recipes=[
                    Recipe(
                        id="open-directory",
                        label="打开文件夹",
                        kind="directory",
                        target=str(path),
                    )
                ],
                primary_recipe_id="open-directory",
            )
            typ = "other"
        projects[key] = DetectedProject(
            id=project_id(path),
            name=path.name,
            path=str(path),
            type=typ,
            manual=True,
            availability="available" if path.is_dir() else "missing",
            recipes=rs.recipes,
            primary_recipe_id=rs.primary_recipe_id,
        )
    return ScanResult(
        scan_id=scan_id or str(uuid4()),
        projects=list(projects.values()),
        root_states=states,
        warnings=warnings,
        started_at=start,
        completed_at=utcnow(),
        limited=limited,
    )
