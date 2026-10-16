from pathlib import Path
from .models import DetectedProject
from .scanner import normalize_project_path
from ...core.config_files import read_json, write_json


class ProjectStore:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "cache" / "projects.json"
        self.warnings = []
        try:
            cached = read_json(self.path, {})
            self.projects = [
                DetectedProject.model_validate(p) for p in cached.get("projects", [])
            ]
            self.scan = cached.get("scan")
        except Exception as e:
            self.projects = []
            self.scan = None
            self.warnings = [str(e)]

    def replace_scan(self, result):
        fresh = {p.id: p for p in result.projects}
        unavailable = [
            normalize_project_path(r)
            for r, state in result.root_states.items()
            if state != "available"
        ]
        for old in self.projects:
            if old.id not in fresh and any(
                Path(normalize_project_path(old.path)).is_relative_to(Path(root))
                for root in unavailable
            ):
                fresh[old.id] = old.model_copy(
                    update={"availability": "root_unavailable"}
                )
        old_times = {p.id: p.discovered_at for p in self.projects}
        for p in fresh.values():
            if p.id in old_times:
                p.discovered_at = old_times[p.id]
        self.projects = list(fresh.values())
        self.scan = result.model_dump(exclude={"projects"})
        write_json(
            self.path,
            {"projects": [p.model_dump() for p in self.projects], "scan": self.scan},
        )
        return self.load_snapshot()

    def load_snapshot(self):
        return {"projects": self.projects, "scan": self.scan}
