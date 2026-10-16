import json, time, psutil
from app.modules.projects.runtime import RuntimeManager
from app.modules.projects.models import Recipe, DetectedProject


def test_npm_cmd_shim_with_space_unicode_and_ampersand_cwd(tmp_path):
    root = tmp_path / "Node 中文 & 空格"
    root.mkdir()
    (root / "package.json").write_text(json.dumps({"scripts": {"dev": "node tree.js"}}))
    (root / "tree.js").write_text(
        "const fs=require('fs'),cp=require('child_process');let c=cp.spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'inherit'});fs.writeFileSync('child.pid',String(c.pid));setInterval(()=>{},1000);",
        encoding="utf-8",
    )
    r = Recipe(
        id="npm",
        label="npm dev",
        kind="command",
        cwd=str(root),
        program="npm",
        args=["run", "dev"],
    )
    p = DetectedProject(
        id="npm",
        name="npm",
        path=str(root),
        type="node",
        recipes=[r],
        primary_recipe_id="npm",
    )
    manager = RuntimeManager(tmp_path / "data", "test")
    try:
        run = manager.launch(p, r)
        deadline = time.monotonic() + 8
        while not (root / "child.pid").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (root / "child.pid").exists(), "npm shim 未运行到测试脚本"
        pid = int((root / "child.pid").read_text())
        assert psutil.pid_exists(pid)
        assert manager.stop(run["id"])["status"] == "stopped"
        deadline = time.monotonic() + 3
        while psutil.pid_exists(pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not psutil.pid_exists(pid)
    finally:
        manager.close()
