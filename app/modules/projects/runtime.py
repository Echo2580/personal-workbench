import logging
import threading
from pathlib import Path
from uuid import uuid4
from .windows_job import WindowsJob, recipe_execution
from .models import utcnow
from ...core.config_files import read_json, write_json, file_lock
from ...core.contracts import WorkbenchError

ACTIVE = ("launching", "running", "stopping")


class RuntimeManager:
    def __init__(self, data_dir, instance_id, adapter=None):
        self.adapter = adapter or WindowsJob()
        self.instance_id = instance_id
        self.lock = threading.RLock()
        self.history_path = Path(data_dir) / "history" / "projects.json"
        self.handles = {}
        self.runs = {}
        self.storage_error = None
        for item in read_json(self.history_path, []):
            if item.get("kind") == "run":
                if item["status"] in ACTIVE:
                    item.update(
                        status="interrupted",
                        ended_at=utcnow(),
                        exit_reason="service_interrupted",
                    )
                self.runs[item["id"]] = item
        self._persist()
        self.closing = threading.Event()
        self.monitor = threading.Thread(
            target=self._loop, name="job-monitor", daemon=True
        )
        self.monitor.start()

    def _persist(self):
        try:
            with file_lock:
                history = read_json(self.history_path, [])
                entries = [x for x in history if x.get("kind") != "run"] + list(
                    self.runs.values()
                )
                entries.sort(key=lambda x: x.get("created_at", ""))
                write_json(self.history_path, entries[-500:])
            self.storage_error = None
        except Exception as e:
            self.storage_error = str(e)
            logging.exception("运行历史保存失败，进程句柄继续由当前实例管理")

    def _loop(self):
        while not self.closing.wait(0.5):
            try:
                with self.lock:
                    self._refresh()
            except Exception:
                logging.exception("Job 状态检查失败")

    def _refresh(self):
        changed = False
        for rid, handle in list(self.handles.items()):
            if self.adapter.active_process_count(handle) == 0:
                run = self.runs[rid]
                code = self.adapter.exit_code(handle)
                run.update(
                    status="stopped"
                    if run.get("stop_requested")
                    else "exited"
                    if code == 0
                    else "failed",
                    ended_at=utcnow(),
                    exit_code=code,
                    exit_reason="user_stop"
                    if run.get("stop_requested")
                    else "process_exit",
                )
                self.adapter.close(handle)
                del self.handles[rid]
                changed = True
        if changed:
            self._persist()

    def launch(self, project, recipe):
        with self.lock:
            self._refresh()
            existing = next(
                (
                    r
                    for r in self.runs.values()
                    if r["project_id"] == project.id and r["status"] in ACTIVE
                ),
                None,
            )
            if existing:
                raise WorkbenchError(
                    "already_running",
                    "此项目已有受管理命令，请先停止。",
                    409,
                    {"run_id": existing["id"]},
                )
            rid = str(uuid4())
            run = {
                "kind": "run",
                "id": rid,
                "project_id": project.id,
                "recipe_id": recipe.id,
                "service_instance_id": self.instance_id,
                "status": "launching",
                "created_at": utcnow(),
                "started_at": None,
                "ended_at": None,
                "exit_code": None,
                "exit_reason": None,
                "error_code": None,
                "project_snapshot": project.model_dump(
                    exclude={"last_run", "active_run"}
                ),
            }
            self.runs[rid] = run
            self._persist()
            try:
                run["execution"] = recipe_execution(recipe)
                handle = self.adapter.start(recipe)
                if getattr(handle, "command_line", ""):
                    run["execution"]["command_line"] = handle.command_line
                self.handles[rid] = handle
                run.update(status="running", started_at=utcnow(), pid=handle.pid)
                self._refresh()
                self._persist()
            except Exception as e:
                run.update(
                    status="failed",
                    ended_at=utcnow(),
                    exit_reason="start_failed",
                    error_code=getattr(e, "code", "start_failed"),
                    error=str(e),
                )
                self._persist()
                raise
            return dict(run)

    def stop(self, rid):
        with self.lock:
            self._refresh()
            run = self.runs.get(rid)
            if not run or run["service_instance_id"] != self.instance_id:
                raise WorkbenchError("run_not_owned", "此运行不属于当前服务实例。", 404)
            if rid not in self.handles:
                return dict(run)
            run.update(status="stopping", stop_requested=True)
            self._persist()
            self.adapter.stop(self.handles[rid])
            self._refresh()
            return dict(run)

    def list_runs(self):
        with self.lock:
            self._refresh()
            return [
                dict(r)
                for r in sorted(
                    self.runs.values(), key=lambda r: r["created_at"], reverse=True
                )
            ][:500]

    def active_count(self):
        return sum(r["status"] in ACTIVE for r in self.list_runs())

    def stop_all(self):
        stopped = []
        failed = []
        for run in self.list_runs():
            if run["status"] not in ACTIVE:
                continue
            try:
                self.stop(run["id"])
                stopped.append(run["id"])
            except Exception as e:
                failed.append(
                    {
                        "run_id": run["id"],
                        "error_code": getattr(e, "code", "stop_failed"),
                        "message": str(e),
                    }
                )
        return {"stopped": stopped, "failed": failed}

    def close(self):
        result = self.stop_all()
        self.closing.set()
        self.monitor.join(2)
        # On interpreter exit Job handles enforce KILL_ON_JOB_CLOSE even after stop errors.
        return result
