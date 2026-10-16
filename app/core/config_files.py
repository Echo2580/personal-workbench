import os
import json
import hashlib
import tempfile
import threading
from pathlib import Path
from dataclasses import dataclass
import tomlkit
from .contracts import WorkbenchError

file_lock = threading.RLock()


class ConfigConflict(WorkbenchError):
    def __init__(self):
        super().__init__(
            "config_conflict",
            "配置已被其他窗口或外部编辑器修改，请重新加载后合并草稿。",
            409,
        )


@dataclass
class ConfigDocument:
    parsed: object
    text: str
    revision: str


def resolve_data_dir(override=None):
    return Path(
        override
        or os.environ.get("WORKBENCH_DATA_DIR")
        or Path(os.environ["LOCALAPPDATA"]) / "PersonalWorkbench"
    )


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_toml(path):
    with file_lock:
        text = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
        try:
            parsed = tomlkit.parse(text)
        except Exception as e:
            raise WorkbenchError(
                "invalid_config",
                f"配置无法解析：{path}。请修复文件或从 .bak 恢复。",
                409,
                str(e),
            ) from e
        return ConfigDocument(parsed, text, digest(text))


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_toml_atomic(path, document, expected_revision):
    with file_lock:
        current = read_toml(path)
        if current.revision != expected_revision:
            raise ConfigConflict()
        text = tomlkit.dumps(document)
        tomlkit.parse(text)
        if current.text:
            atomic_text(
                Path(path).with_suffix(Path(path).suffix + ".bak"), current.text
            )
        atomic_text(path, text)
        return digest(text)


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (ValueError, OSError) as e:
        raise WorkbenchError(
            "invalid_data", f"本地数据无法读取：{path}", 409, str(e)
        ) from e


def write_json(path, value):
    with file_lock:
        atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2))
