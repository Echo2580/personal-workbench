import pytest
from pathlib import Path

from app.core.config_files import (
    ConfigConflict,
    read_toml,
    resolve_data_dir,
    write_toml_atomic,
)


def test_data_dir_defaults_inside_project(tmp_path, monkeypatch):
    """数据根目录跟着项目走：默认 <项目根>/data，不再写 %LOCALAPPDATA%。"""
    monkeypatch.delenv("WORKBENCH_DATA_DIR", raising=False)
    project_root = Path(__file__).resolve().parents[2]  # tests/unit -> tests -> 项目根
    assert resolve_data_dir() == project_root / "data"
    # 显式参数与环境变量优先级更高（测试/预览仍可隔离使用临时目录）
    assert resolve_data_dir(tmp_path) == tmp_path
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path / "from-env"))
    assert resolve_data_dir() == tmp_path / "from-env"
    assert resolve_data_dir(tmp_path) == tmp_path


def test_comments_unicode_conflicts_and_backup(tmp_path):
    p = tmp_path / "中文目录" / "settings.toml"
    p.parent.mkdir()
    p.write_text('# 注释\nkeep = "原值"\n', encoding="utf-8")
    doc = read_toml(p)
    doc.parsed["roots"] = ["D:/中文 空格"]
    revision = write_toml_atomic(p, doc.parsed, doc.revision)
    assert "# 注释" in p.read_text(encoding="utf-8")
    assert read_toml(p).parsed["keep"] == "原值"
    assert p.with_suffix(".toml.bak").read_text(encoding="utf-8").startswith("# 注释")
    with pytest.raises(ConfigConflict):
        write_toml_atomic(p, doc.parsed, doc.revision)
    assert read_toml(p).revision == revision


def test_replace_failure_preserves_original(tmp_path, monkeypatch):
    import os

    p = tmp_path / "config.toml"
    p.write_text("x = 1", encoding="utf-8")
    d = read_toml(p)
    d.parsed["x"] = 2

    def fail(*args):
        raise OSError("模拟原子替换失败")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        write_toml_atomic(p, d.parsed, d.revision)
    assert read_toml(p).parsed["x"] == 1
