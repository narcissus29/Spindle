"""Wheel -> editor handshake with the real editor process."""
from harness import *
import subprocess, signal
from pathlib import Path
from PyQt6.QtCore import QUrl
from app.single_instance import SingleInstance
from app.editor import launcher
inst = SingleInstance(); assert inst.listen()
def on_cmd(cmd):
    print("cmd", cmd, flush=True)
    if cmd == "editor-ready": b.editor_ready()
    elif cmd.startswith("editor-failed "): b.editor_failed(cmd.split(" ", 1)[1])
inst.commandReceived.connect(on_cmd)
def kill_editors():
    import os
    for pid in os.listdir("/proc"):
        if not pid.isdigit(): continue
        try: argv = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
        except OSError: continue
        if len(argv) > 2 and argv[1].endswith(b"main.py") and argv[2] == b"--editor":
            os.kill(int(pid), 15)
launched = []
def open_editor(tool, path):
    launched.append((tool, Path(path).name)); launcher.launch(tool, Path(path))
b.editorRequested.connect(open_editor)
D = Path(S) / "ed"
D.mkdir(exist_ok=True)
from tests.conftest import make_photo
make_photo(D / "photo.jpg", size=(800, 500))
closes = []; b.closeRequested.connect(lambda: closes.append(time.monotonic()))
seq = []
def later(ms, fn): seq.append((ms, fn))
def go(i=0):
    if i >= len(seq): finish(); return
    ms, fn = seq[i]; QTimer.singleShot(ms, lambda: (fn(), go(i + 1)))
def finish():
    kill_editors(); app.exit(0)
st = {}
def s1():
    w.show_wheel()
def s2():
    drag([QUrl.fromLocalFile(str(D / "photo.jpg"))])
    names = [o["name"] for o in b.options]; st["t0"] = time.monotonic()
    b.drop(names.index("Crop"))
    check("pill says Opening…", b.statusText == "Opening…", b.statusText)
    check("editor launched for Crop", launched == [("crop", "photo.jpg")], str(launched))
def s3():
    check("wheel closed once the editor was up", bool(closes), f"{(closes[0]-st['t0'])*1000:.0f} ms" if closes else "")
    check("pill cleared", b.statusText == "", b.statusText)
def s4():
    kill_editors()
    w.show_wheel()
def s5():
    from tests.conftest import make_pdf
    make_pdf(D / "locked.pdf", pages=1, password="pw")
    drag([QUrl.fromLocalFile(str(D / "locked.pdf"))])
    b.park(); b.switchWheel()
    names = [o["name"] for o in b.options]
    b.activate(names.index("Redact"))
def s6():
    check("failure reason shown in the pill", b.statusText == "Password-protected PDF", b.statusText)
    st["n"] = len(closes)
def s7():
    check("then the wheel closes", len(closes) > st["n"])
def s8():
    kill_editors()
    w.show_wheel()
def s9():
    launched.clear(); st["n"] = len(closes)
    drag([QUrl.fromLocalFile(str(D / "photo.jpg"))])
    names = [o["name"] for o in b.options]
    b.drop(names.index("Metadata"))
    check("one file on Metadata opens the Info viewer", launched == [("metadata", "photo.jpg")], str(launched))
def s10():
    check("wheel closed once the viewer was up", len(closes) > st["n"])
later(400, s1); later(400, s2); later(4000, s3); later(300, s4); later(500, s5); later(1300, s6); later(2500, s7)
later(300, s8); later(500, s9); later(4000, s10)
go(); app.exec()
print("FAILS:", fails)
