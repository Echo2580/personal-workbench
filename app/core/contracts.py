from dataclasses import dataclass, field
from typing import Callable, Any


@dataclass
class ModuleSummary:
    metrics: list = field(default_factory=list)
    recent_links: list = field(default_factory=list)
    availability: str = "uninitialized"


@dataclass
class ModuleDefinition:
    id: str
    title: str
    description: str
    icon: str
    route: str | None
    status: str
    router: Any = None
    summary_provider: Callable | None = None
    settings_route: str | None = None

    def public(self):
        summary = self.summary_provider() if self.summary_provider else ModuleSummary()
        if isinstance(summary, ModuleSummary):
            summary = summary.__dict__
        return {
            k: getattr(self, k)
            for k in (
                "id",
                "title",
                "description",
                "icon",
                "route",
                "status",
                "settings_route",
            )
        } | {"summary": summary}


class WorkbenchError(Exception):
    def __init__(self, code, message, status=400, details=None, recovery_action=None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.details, self.recovery_action = details, recovery_action
