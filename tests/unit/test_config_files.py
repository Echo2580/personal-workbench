import pytest
from app.core.config_files import read_toml, write_toml_atomic, ConfigConflict


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
