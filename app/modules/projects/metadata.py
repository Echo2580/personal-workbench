"""Bounded, non-executable project display metadata."""

import json
import re
import tomllib
from pathlib import Path

from .detectors import limited_read, plain_file


def _name(value):
    if not isinstance(value, str) or len(value) > 1024:
        return ""
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"<[^>]*>", "", value).strip(" #*`\t")
    if not value or len(value) > 120 or any(ord(c) < 32 for c in value):
        return ""
    if value.casefold() in {
        "readme",
        "readme.md",
        "overview",
        "introduction",
        "项目说明",
        "项目介绍",
        "快速开始",
        "简介",
        "安装",
    }:
        return ""
    return value


def project_name(path):
    path = Path(path)
    for filename in ("package.json", "pyproject.toml", "Cargo.toml"):
        source = path / filename
        if not plain_file(source):
            continue
        try:
            data = (
                json.loads(limited_read(source))
                if filename.endswith(".json")
                else tomllib.loads(limited_read(source))
            )
            if not isinstance(data, dict):
                continue
            package = (
                data
                if filename == "package.json"
                else data.get(
                    "project" if filename == "pyproject.toml" else "package", {}
                )
            )
            name = _name(package.get("name")) if isinstance(package, dict) else ""
            if name:
                return name
        except (OSError, ValueError, TypeError):
            continue
    try:
        readmes = sorted(
            (
                p
                for p in path.iterdir()
                if p.name.casefold() in {"readme.md", "readme.markdown"}
                and plain_file(p)
            ),
            key=lambda p: p.name,
        )
        for source in readmes:
            fence = ""
            for line in limited_read(source).splitlines():
                boundary = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
                if boundary:
                    marker = boundary.group(1)
                    if not fence:
                        fence = marker
                    elif marker[0] == fence[0] and len(marker) >= len(fence):
                        fence = ""
                    continue
                if fence:
                    continue
                match = re.fullmatch(r" {0,3}#\s+(.+)", line) or re.fullmatch(
                    r"\s*<h1\b[^>]*>(.*?)</h1>\s*", line, re.IGNORECASE
                )
                if match:
                    name = _name(match.group(1))
                    if name:
                        return name
                    break
    except (OSError, ValueError):
        pass
    return path.name
