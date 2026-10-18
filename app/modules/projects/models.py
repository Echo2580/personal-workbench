from datetime import datetime, timezone
from typing import Annotated, Literal
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from urllib.parse import urlsplit


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectSettings(DTO):
    schema_version: int = 1
    roots: list[str] = Field(default_factory=list)
    default_python: str = ""
    scan_interval_seconds: int = Field(default=15, ge=5, le=300)
    max_depth: int = Field(default=5, ge=1, le=10)
    max_directories: int = Field(default=10000, ge=1, le=10000)
    excluded_names: list[str] = Field(
        default_factory=lambda: [
            ".git",
            ".venv",
            "venv",
            "node_modules",
            "__pycache__",
            "dist",
            "build",
            "coverage",
            ".workbuddy",
            ".claude",
            ".qwen",
            ".idea",
            ".vscode",
            "logs",
            "daily_reports",
        ]
    )


class Recipe(DTO):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=120)
    kind: Literal["command", "app", "directory", "url"]
    cwd: str | None = None
    program: str | None = None
    args: list[str] = Field(default_factory=list)
    shell_command: str | None = None
    target: str | None = None

    @model_validator(mode="after")
    def valid(self):
        if not self.label.strip():
            raise ValueError("名称不能为空")
        if self.kind == "command":
            if (
                bool(self.program) == bool(self.shell_command)
                or not self.cwd
                or self.target
            ):
                raise ValueError("命令需要工作目录，且原生命令和 CMD 命令必须二选一")
            if self.shell_command and self.args:
                raise ValueError("CMD 命令不接受独立参数")
        elif self.kind == "app":
            if not self.program or not self.cwd or self.shell_command or self.target:
                raise ValueError("应用需要程序与工作目录")
        else:
            if (
                not self.target
                or self.cwd
                or self.program
                or self.args
                or self.shell_command
            ):
                raise ValueError("打开配方仅接受目标")
            if self.kind == "url":
                u = urlsplit(self.target)
                # 静态文件是否位于项目目录内由 service 再校验；这里只限制 http(s) 或 .html 绝对路径。
                if u.scheme not in ("http", "https") or not u.netloc:
                    from pathlib import Path

                    if not (
                        Path(self.target).is_absolute()
                        and Path(self.target).suffix.lower() == ".html"
                    ):
                        raise ValueError("只允许 http/https 或项目内 .html 绝对路径")
        return self


class RecipeSet(DTO):
    recipes: list[Recipe] = Field(min_length=1)
    primary_recipe_id: str

    @model_validator(mode="after")
    def valid(self):
        ids = [r.id for r in self.recipes]
        if len(set(ids)) != len(ids) or self.primary_recipe_id not in ids:
            raise ValueError("配方 ID 需要唯一且主配方必须存在")
        return self


class ProjectNameInput(DTO):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ]

    @field_validator("name")
    @classmethod
    def single_line(cls, value):
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("项目名称不能包含换行或控制字符")
        return value


class ProjectName(ProjectNameInput):
    path: str


class RemovedProject(DTO):
    path: str
    name: str
    removed_at: str


class Detection(DTO):
    path: str
    type: str
    entry_candidates: list[str] = Field(default_factory=list)
    package_manager: str = "npm"
    scripts: list[str] = Field(default_factory=list)
    workspaces: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    # 识别到的框架（python: django；node: vite/next/nuxt/astro/svelte/angular），供配方生成使用。
    framework: str = ""


class DetectedProject(DTO):
    id: str
    name: str
    default_name: str | None = None
    has_custom_name: bool = False
    path: str
    type: str
    discovered_at: str = Field(default_factory=utcnow)
    availability: str = "available"
    recipe_source: str = "auto"
    recipes: list[Recipe]
    primary_recipe_id: str
    evidence: list[str] = Field(default_factory=list)
    manual: bool = False
    last_action_at: str | None = None
    active_run: dict | None = None
    last_run: dict | None = None


Project = DetectedProject


class ScanResult(DTO):
    scan_id: str
    projects: list[DetectedProject]
    root_states: dict[str, str]
    warnings: list[str]
    started_at: str
    completed_at: str
    limited: bool = False
