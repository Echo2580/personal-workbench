from pathlib import Path
from test_instance import wait_instance, call


def test_pythonw_production_entry_and_fresh_data(tmp_path):
    import sys, subprocess

    pythonw = str(Path(sys.executable).with_name("pythonw.exe"))
    process = subprocess.Popen(
        [pythonw, "-m", "app.launcher", "--no-browser", "--data-dir", str(tmp_path)],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        info = wait_instance(tmp_path)
        assert call(info, "/projects")["projects"] == []
        call(info, "/system/shutdown", {"confirmed_stop_running": True})
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
