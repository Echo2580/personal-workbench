import threading
from app.core.shutdown import ShutdownCoordinator


def test_shutdown_accepts_module_neutral_hooks():
    blocked = []
    exited = []
    coordinator = ShutdownCoordinator(
        lock=threading.RLock(),
        running_items=lambda: [{"label": "备份任务", "id": "work"}],
        stop_all=lambda: {"stopped": ["work"], "failed": []},
        block_actions=lambda value: blocked.append(value),
        on_shutdown=lambda: exited.append(True),
    )
    assert coordinator.preview() == {
        "running_items": [{"label": "备份任务", "id": "work"}]
    }
    assert coordinator.request(True)["stopped"] == ["work"]
    assert blocked == [True] and exited == [True]
