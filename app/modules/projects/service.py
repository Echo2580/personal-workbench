import threading
from pathlib import Path
from uuid import uuid4
import tomlkit
from pydantic import ValidationError
from .models import (
    ProjectSettings,
    RecipeSet,
    DetectedProject,
    RemovedProject,
    ProjectName,
    utcnow,
)
from .scanner import scan_roots, project_id, is_link
from .detectors import detect_project
from .recipes import generate_recipes, recipe_fingerprint
from .settings import validate_settings
from .store import ProjectStore
from ...core.config_files import read_toml, write_toml_atomic, read_json, write_json
from ...core.contracts import WorkbenchError


class ProjectService:
    def __init__(self, data_dir, instance_id):
        self.data_dir = Path(data_dir)
        self.instance_id = instance_id
        self.lock = threading.RLock()
        self.runtime = None
        self.shutting_down = False
        self.settings_path = self.data_dir / "settings.toml"
        self.projects_path = self.data_dir / "projects.toml"
        for path, defaults in [
            (self.settings_path, ProjectSettings().model_dump()),
            (
                self.projects_path,
                {
                    "schema_version": 1,
                    "manual_projects": [],
                    "overrides": {},
                    "removed_projects": {},
                    "project_names": {},
                },
            ),
        ]:
            d = read_toml(path)
            if not d.text:
                write_toml_atomic(path, tomlkit.item(defaults), d.revision)
        self.store = ProjectStore(self.data_dir)
        self.settings = ProjectSettings()
        self.manual = []
        self.overrides = {}
        self.removed = {}
        self.names = {}
        self.projects_revision = None
        self.config_warning = None
        self.scan_id = None
        self.is_scanning = False
        self.worker = None
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.history_path = self.data_dir / "history" / "projects.json"
        self.approvals_path = self.data_dir / "history" / "approvals.json"
        self.refresh_config()

    def refresh_config(self):
        try:
            self._read_config()
        except (ValidationError, KeyError, TypeError) as e:
            raise WorkbenchError(
                "invalid_config",
                "配置字段格式无效，请修复 TOML 文件或从 .bak 恢复。",
                409,
                str(e),
            ) from e

    def _read_config(self):
        settings = ProjectSettings.model_validate(
            read_toml(self.settings_path).parsed.unwrap()
        )
        document = read_toml(self.projects_path)
        doc = document.parsed.unwrap()
        manual = doc.get("manual_projects", [])
        overrides = doc.get("overrides", {})
        names = doc.get("project_names", {})
        if not isinstance(names, dict):
            raise WorkbenchError("invalid_config", "项目自定义名称格式不正确。", 409)
        valid_names = {}
        for pid, row in names.items():
            record = ProjectName.model_validate(row)
            if not Path(record.path).is_absolute() or project_id(record.path) != pid:
                raise WorkbenchError(
                    "invalid_config", "项目名称记录的路径与 ID 不一致。", 409
                )
            valid_names[pid] = record.model_dump()
        removed = doc.get("removed_projects", {})
        if not isinstance(removed, dict):
            raise WorkbenchError("invalid_config", "已移除项目列表格式不正确。", 409)
        for pid, row in removed.items():
            record = RemovedProject.model_validate(row)
            if not Path(record.path).is_absolute() or project_id(record.path) != pid:
                raise WorkbenchError(
                    "invalid_config", "已移除项目的路径与 ID 不一致。", 409
                )
        if not isinstance(manual, list) or not isinstance(overrides, dict):
            raise WorkbenchError(
                "invalid_config", "projects.toml 的登记或覆盖格式不正确。", 409
            )
        for row in manual:
            if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                raise WorkbenchError("invalid_config", "手动项目需要 path 字段。", 409)
        for override in overrides.values():
            RecipeSet.model_validate(
                {k: override[k] for k in ("recipes", "primary_recipe_id")}
            )
        self.settings, self.manual, self.overrides = settings, manual, overrides
        self.removed = removed
        self.names = valid_names
        self.projects_revision = document.revision
        self.config_warning = None

    def safe_refresh(self):
        try:
            self.refresh_config()
        except Exception as e:
            self.config_warning = str(e)

    def start(self):
        def loop():
            while not self.stopping.is_set():
                self.request_scan()
                while self.is_scanning and not self.stopping.wait(0.05):
                    pass
                self.wake.wait(self.settings.scan_interval_seconds)
                self.wake.clear()

        self.coordinator = threading.Thread(
            target=loop, name="project-scan-scheduler", daemon=True
        )
        self.coordinator.start()

    def close(self):
        self.stopping.set()
        self.wake.set()
        if hasattr(self, "coordinator"):
            self.coordinator.join(3)
        if self.worker:
            self.worker.join(10)

    def request_scan(self):
        with self.lock:
            if self.is_scanning:
                return {"scan_id": self.scan_id}
            self.safe_refresh()
            settings = self.settings.model_copy(deep=True)
            manual = [Path(x["path"]) for x in self.manual]
            self.scan_id = str(uuid4())
            scan_id = self.scan_id
            self.is_scanning = True

            def work():
                try:
                    result = scan_roots(settings, manual, scan_id)
                    with self.lock:
                        self.store.replace_scan(result)
                except Exception as e:
                    with self.lock:
                        self.store.warnings = [f"扫描失败：{e}"]
                finally:
                    with self.lock:
                        self.is_scanning = False

            self.worker = threading.Thread(
                target=work, name="project-scan", daemon=True
            )
            self.worker.start()
            return {"scan_id": scan_id}

    def runs(self):
        return self.runtime.list_runs() if self.runtime else []

    def snapshot(self):
        with self.lock:
            self.safe_refresh()
            projects = {
                p.id: p.model_copy(deep=True)
                for p in self.store.projects
                if not p.manual
                or any(project_id(x["path"]) == p.id for x in self.manual)
            }
            for row in self.manual:
                pid = project_id(row["path"])
                if pid not in projects:
                    d = (
                        detect_project(Path(row["path"]), self.settings)
                        if Path(row["path"]).is_dir()
                        else None
                    )
                    if d:
                        rs = generate_recipes(d, self.settings)
                        typ = d.type
                    else:
                        from .models import Recipe

                        rs = RecipeSet(
                            recipes=[
                                Recipe(
                                    id="open-directory",
                                    label="打开文件夹",
                                    kind="directory",
                                    target=row["path"],
                                )
                            ],
                            primary_recipe_id="open-directory",
                        )
                        typ = "other"
                    projects[pid] = DetectedProject(
                        id=pid,
                        name=row.get("name") or Path(row["path"]).name,
                        path=row["path"],
                        type=typ,
                        recipes=rs.recipes,
                        primary_recipe_id=rs.primary_recipe_id,
                    )
                projects[pid].manual = True
                if row.get("name"):
                    projects[pid].name = row["name"]
            # Recalculate auto recipes with current environment settings, without executing project code.
            history = read_json(self.history_path, [])
            for p in projects.values():
                if p.id in self.overrides:
                    o = self.overrides[p.id]
                    rs = RecipeSet.model_validate(
                        {k: o[k] for k in ("recipes", "primary_recipe_id")}
                    )
                    p.recipes = rs.recipes
                    p.primary_recipe_id = rs.primary_recipe_id
                    p.recipe_source = "manual"
                elif Path(p.path).is_dir():
                    d = detect_project(Path(p.path), self.settings)
                    if d:
                        rs = generate_recipes(d, self.settings)
                        p.recipes = rs.recipes
                        p.primary_recipe_id = rs.primary_recipe_id
                if not Path(p.path).is_dir() and p.availability != "root_unavailable":
                    p.availability = "missing"
                actions = [a for a in history if a.get("project_id") == p.id]
                if actions:
                    p.last_action_at = max(a.get("created_at", "") for a in actions)
            for run in self.runs():
                pid = run["project_id"]
                if pid not in projects and run["status"] in (
                    "launching",
                    "running",
                    "stopping",
                ):
                    saved = run.get("project_snapshot")
                    if saved:
                        projects[pid] = DetectedProject.model_validate(saved)
                if pid in projects:
                    p = projects[pid]
                    if (
                        p.last_run is None
                        or run["created_at"] > p.last_run["created_at"]
                    ):
                        p.last_run = run
                    if run["status"] in ("launching", "running", "stopping"):
                        p.active_run = run
            for p in projects.values():
                p.default_name = p.default_name or p.name
                p.has_custom_name = p.id in self.names
                p.name = (
                    self.names[p.id]["name"] if p.has_custom_name else p.default_name
                )
            warnings = list(self.store.warnings) + (self.store.scan or {}).get(
                "warnings", []
            )
            if self.config_warning:
                warnings.append(self.config_warning)
            return {
                # Active runs remain reachable even if an external edit hides their project.
                "projects": [
                    p.model_dump()
                    for p in projects.values()
                    if p.id not in self.removed or p.active_run
                ],
                "revision": self.projects_revision,
                "capabilities": {"project_names": True},
                "scan": self.store.scan,
                "is_scanning": self.is_scanning,
                "scan_id": self.scan_id,
                "warnings": warnings,
                "roots": self.settings.roots,
            }

    def project(self, pid):
        for p in self.snapshot()["projects"]:
            if p["id"] == pid:
                return DetectedProject.model_validate(p)
        raise WorkbenchError("project_not_found", "找不到此项目，请重新扫描。", 404)

    def get_recipes(self, pid):
        with self.lock:
            self.refresh_config()
            p = self.project(pid)
            return {
                "project_id": pid,
                "source": p.recipe_source,
                "revision": read_toml(self.projects_path).revision,
                "recipes": [
                    r.model_dump() | {"fingerprint": recipe_fingerprint(pid, r)}
                    for r in p.recipes
                ],
                "primary_recipe_id": p.primary_recipe_id,
            }

    def check_recipe_paths(self, p, rs):
        for r in rs.recipes:
            if r.kind in ("command", "app") and (
                not Path(r.cwd).is_absolute() or not Path(r.cwd).is_dir()
            ):
                raise WorkbenchError(
                    "invalid_cwd",
                    "工作目录需要存在的绝对路径。",
                    422,
                    {"recipe_id": r.id},
                )
            if r.kind == "url" and not r.target.startswith(("http://", "https://")):
                target = Path(r.target)
                if (
                    target.resolve() != (Path(p.path) / "index.html").resolve()
                    or not target.is_file()
                ):
                    raise WorkbenchError(
                        "invalid_target", "静态网页只允许本项目已有的 index.html。", 422
                    )
            if r.kind == "directory" and (
                not Path(r.target).is_absolute() or not Path(r.target).is_dir()
            ):
                raise WorkbenchError(
                    "invalid_target", "文件夹目标需要存在的绝对路径。", 422
                )

    def save_recipes(self, pid, draft, expected_revision):
        with self.lock:
            self.refresh_config()
            p = self.project(pid)
            self.check_recipe_paths(p, draft)
            if p.active_run:
                rid = p.active_run["recipe_id"]
                before = next((r for r in p.recipes if r.id == rid), None)
                after = next((r for r in draft.recipes if r.id == rid), None)
                if before != after or p.primary_recipe_id != draft.primary_recipe_id:
                    raise WorkbenchError(
                        "running_recipe_locked",
                        "请先停止项目，再修改运行配方或主配方。",
                        409,
                    )
            d = read_toml(self.projects_path)
            if "overrides" not in d.parsed:
                d.parsed["overrides"] = tomlkit.table()
            d.parsed["overrides"][pid] = {
                "path": p.path,
                **draft.model_dump(exclude_none=True),
            }
            write_toml_atomic(self.projects_path, d.parsed, expected_revision)
            self.refresh_config()
            return self.get_recipes(pid)

    def reset_override(self, pid, expected_revision):
        with self.lock:
            self.refresh_config()
            p = self.project(pid)
            if p.active_run:
                raise WorkbenchError(
                    "running_recipe_locked", "运行中不能恢复自动识别，请先停止。", 409
                )
            d = read_toml(self.projects_path)
            if pid in d.parsed.get("overrides", {}):
                del d.parsed["overrides"][pid]
            write_toml_atomic(self.projects_path, d.parsed, expected_revision)
            self.refresh_config()
            return self.get_recipes(pid)

    def get_settings(self):
        with self.lock:
            self.refresh_config()
            return {
                "settings": self.settings.model_dump(),
                "revision": read_toml(self.settings_path).revision,
                "root_states": (self.store.scan or {}).get("root_states", {}),
            }

    def save_settings(self, draft, expected_revision):
        with self.lock:
            draft = validate_settings(draft)
            d = read_toml(self.settings_path)
            for k, v in draft.model_dump().items():
                d.parsed[k] = v
            write_toml_atomic(self.settings_path, d.parsed, expected_revision)
            self.refresh_config()
            self.wake.set()
            self.request_scan()
            return self.get_settings()

    def add_manual_project(self, path, name=None):
        from .scanner import normalize_project_path

        p = Path(path)
        if not p.is_absolute() or not p.is_dir() or is_link(p):
            raise WorkbenchError(
                "invalid_project_path", "请填写存在且不是链接的目录绝对路径。", 422
            )
        path = normalize_project_path(p)
        with self.lock:
            self.refresh_config()
            d = read_toml(self.projects_path)
            if project_id(path) in self.removed:
                raise WorkbenchError(
                    "project_removed",
                    "该项目已从工作台移除，请在设置的已移除项目中恢复。",
                    409,
                )
            if not any(project_id(x["path"]) == project_id(path) for x in self.manual):
                row = {"path": path}
                if name:
                    row["name"] = name
                d.parsed["manual_projects"].append(row)
                write_toml_atomic(self.projects_path, d.parsed, d.revision)
                self.refresh_config()
            return self.project(project_id(path)).model_dump()

    def rename_project(self, pid, name, expected_revision):
        with self.lock:
            self.refresh_config()
            p = self.project(pid)
            record = ProjectName(path=p.path, name=name)
            d = read_toml(self.projects_path)
            if "project_names" not in d.parsed:
                d.parsed["project_names"] = tomlkit.table()
            d.parsed["project_names"][pid] = record.model_dump()
            write_toml_atomic(self.projects_path, d.parsed, expected_revision)
            self.refresh_config()
            return {
                "project": self.project(pid).model_dump(),
                "revision": self.projects_revision,
            }

    def reset_project_name(self, pid, expected_revision):
        with self.lock:
            self.refresh_config()
            self.project(pid)
            d = read_toml(self.projects_path)
            if pid in d.parsed.get("project_names", {}):
                del d.parsed["project_names"][pid]
            write_toml_atomic(self.projects_path, d.parsed, expected_revision)
            self.refresh_config()
            return {
                "project": self.project(pid).model_dump(),
                "revision": self.projects_revision,
            }

    def removed_projects(self):
        with self.lock:
            self.refresh_config()
            return {
                "projects": [
                    {
                        **row,
                        "id": pid,
                        "name": self.names.get(pid, {}).get("name", row["name"]),
                    }
                    for pid, row in self.removed.items()
                ],
                "revision": self.projects_revision,
            }

    def remove_project(self, pid, expected_revision):
        with self.lock:
            self.refresh_config()
            p = self.project(pid)
            if p.active_run:
                raise WorkbenchError(
                    "project_running", "请先停止项目，再从工作台移除。", 409
                )
            d = read_toml(self.projects_path)
            if "removed_projects" not in d.parsed:
                d.parsed["removed_projects"] = tomlkit.table()
            d.parsed["removed_projects"][pid] = {
                "path": p.path,
                "name": p.name,
                "removed_at": utcnow(),
            }
            write_toml_atomic(self.projects_path, d.parsed, expected_revision)
            self.refresh_config()
            return {"removed": True}

    def restore_project(self, pid, expected_revision):
        with self.lock:
            self.refresh_config()
            if pid not in self.removed:
                raise WorkbenchError(
                    "project_not_removed", "该项目不在已移除列表中，请刷新列表。", 404
                )
            d = read_toml(self.projects_path)
            del d.parsed["removed_projects"][pid]
            write_toml_atomic(self.projects_path, d.parsed, expected_revision)
            self.refresh_config()
            self.request_scan()
            return {"restored": True}

    def remove_manual(self, pid):
        with self.lock:
            self.refresh_config()
            p = self.project(pid)
            if p.active_run:
                raise WorkbenchError(
                    "project_running", "请先停止运行再移除手动登记。", 409
                )
            d = read_toml(self.projects_path)
            d.parsed["manual_projects"] = [
                x for x in self.manual if project_id(x["path"]) != pid
            ]
            write_toml_atomic(self.projects_path, d.parsed, d.revision)
            self.refresh_config()
            self.request_scan()
            return {"removed": True}

    def saved_recipe(self, pid, rid, fingerprint):
        self.refresh_config()
        p = self.project(pid)
        r = next((r for r in p.recipes if r.id == rid), None)
        if not r:
            raise WorkbenchError("recipe_not_found", "配方已删除，请刷新。", 404)
        if recipe_fingerprint(pid, r) != fingerprint:
            raise WorkbenchError(
                "recipe_changed", "配方已改变，请重新查看并确认。", 409
            )
        return p, r

    def approve(self, pid, rid, fingerprint):
        with self.lock:
            self.saved_recipe(pid, rid, fingerprint)
            approvals = read_json(self.approvals_path, {})
            approvals[pid + ":" + rid] = fingerprint
            write_json(self.approvals_path, approvals)
            return {"approved": True}

    def execute(self, pid, rid, fingerprint):
        with self.lock:
            if self.shutting_down:
                raise WorkbenchError("shutting_down", "工作台正在退出。", 409)
            p, r = self.saved_recipe(pid, rid, fingerprint)
            if read_json(self.approvals_path, {}).get(pid + ":" + rid) != fingerprint:
                raise WorkbenchError(
                    "approval_required", "首次执行或配方变更后，请先确认完整配方。", 409
                )
            self.check_recipe_paths(p, RecipeSet(recipes=[r], primary_recipe_id=r.id))
            if not Path(p.path).is_dir():
                raise WorkbenchError(
                    "project_missing", "项目目录不存在，请恢复目录。", 422
                )
            if r.kind == "command":
                result = {"run": self.runtime.launch(p, r)}
            else:
                from .actions import OpenActionService

                result = OpenActionService().execute(r)
                history = read_json(self.history_path, [])
                history.append(
                    {
                        "kind": "action",
                        "project_id": pid,
                        "recipe_id": rid,
                        "created_at": utcnow(),
                    }
                )
                write_json(self.history_path, history[-500:])
            return result

    def shutdown_items(self):
        with self.lock:
            self.safe_refresh()
            manual_names = {
                project_id(row["path"]): row.get("name") for row in self.manual
            }
            return [
                {
                    "id": r["id"],
                    "label": self.names.get(r["project_id"], {}).get("name")
                    or manual_names.get(r["project_id"])
                    or r.get("project_snapshot", {}).get("default_name")
                    or r.get("project_snapshot", {}).get("name", r["project_id"]),
                }
                for r in self.runs()
                if r["status"] in ("launching", "running", "stopping")
            ]

    def block_actions(self, value):
        self.shutting_down = value

    def summary(self):
        s = self.snapshot()
        ps = s["projects"]
        return {
            "metrics": [
                {"label": "项目", "value": len(ps)},
                {"label": "运行中", "value": sum(bool(p["active_run"]) for p in ps)},
            ],
            "recent_links": [
                {
                    "label": p["name"],
                    "route": "/projects",
                    "params": {"project": p["id"]},
                }
                for p in sorted(
                    [p for p in ps if p["last_action_at"]],
                    key=lambda p: p["last_action_at"],
                    reverse=True,
                )[:4]
            ],
            "availability": "尚未配置扫描目录"
            if not s["roots"]
            else "扫描中"
            if s["is_scanning"]
            else "最近扫描完成"
            if s["scan"]
            else "等待首次扫描",
        }
