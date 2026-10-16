"""Module-neutral shutdown orchestration. Hooks own their private runtime models."""

from .contracts import WorkbenchError


class ShutdownCoordinator:
    def __init__(self, *, lock, running_items, stop_all, block_actions, on_shutdown):
        self.lock = lock
        self.running_items = running_items
        self.stop_all = stop_all
        self.block_actions = block_actions
        self.on_shutdown = on_shutdown

    def preview(self):
        with self.lock:
            return {"running_items": self.running_items()}

    def request(self, confirmed_stop_running):
        with self.lock:
            active = self.running_items()
            if active and not confirmed_stop_running:
                raise WorkbenchError(
                    "running_work", "退出前需要确认停止受管理任务。", 409, active
                )
            self.block_actions(True)
            result = self.stop_all()
            if result["failed"]:
                self.block_actions(False)
                raise WorkbenchError(
                    "shutdown_stop_failed",
                    "部分任务停止失败，服务保持运行。请重试停止。",
                    500,
                    result,
                )
            self.on_shutdown()
            return {"status": "shutting_down", **result}
