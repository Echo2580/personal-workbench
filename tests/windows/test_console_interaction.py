import subprocess, sys
from app.modules.projects.windows_job import WindowsJob
from app.modules.projects.models import Recipe
from test_job_lifecycle import wait_for


def test_keyboard_input_in_independent_console(tmp_path):
    result = tmp_path / "input.txt"
    ready = tmp_path / "ready.txt"
    program = tmp_path / "input.py"
    program.write_text(
        "import sys\nfrom pathlib import Path\nPath(sys.argv[2]).write_text('ready')\ns=input('Enter: ')\nPath(sys.argv[1]).write_text(s,encoding='utf-8')\n",
        encoding="utf-8",
    )
    adapter = WindowsJob()
    job = adapter.start(
        Recipe(
            id="x",
            label="交互",
            kind="command",
            cwd=str(tmp_path),
            program=sys.executable,
            args=[str(program), str(result), str(ready)],
        )
    )
    try:
        wait_for(ready.exists)
        helper = tmp_path / "keyboard.py"
        helper.write_text(
            r"""import sys,win32console,win32con
try: win32console.FreeConsole()
except Exception: pass
win32console.AttachConsole(int(sys.argv[1]))
h=win32console.GetStdHandle(win32console.STD_INPUT_HANDLE)
records=[]
for c in 'hello-console\r':
    for down in [True,False]:
        r=win32console.PyINPUT_RECORDType(win32console.KEY_EVENT)
        r.Char=c;r.KeyDown=down;r.RepeatCount=1;r.VirtualKeyCode=13 if c=='\r' else 189 if c=='-' else ord(c.upper())
        records.append(r)
h.WriteConsoleInput(records)
win32console.FreeConsole()
""",
            encoding="utf-8",
        )
        source = helper.read_text(encoding="utf-8")
        helper.write_text(
            "import traceback,sys\nfrom pathlib import Path\ntry:\n"
            + "".join("    " + line + "\n" for line in source.splitlines())
            + "except BaseException:\n    Path(sys.argv[2]).write_text(traceback.format_exc(),encoding='utf-8')\n    raise\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            [sys.executable, str(helper), str(job.pid), str(tmp_path / "error.txt")],
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=5,
        )
        assert completed.returncode == 0, (tmp_path / "error.txt").read_text(
            encoding="utf-8"
        )
        wait_for(result.exists)
        assert result.read_text(encoding="utf-8") == "hello-console"
        wait_for(lambda: adapter.active_process_count(job) == 0)
    finally:
        adapter.stop(job)
        adapter.close(job)
