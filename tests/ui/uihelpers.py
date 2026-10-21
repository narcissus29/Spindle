"""Test handlers for UI suites; imported by the helper process (PYTHONPATH)."""
import os, time
def record(path, option, ctx):
    delay = float(os.environ.get("SPINDLE_UI_DELAY_" + option.split(":")[-1].replace(" ", "_"), "0"))
    for i in range(10):
        time.sleep(delay / 10)
        ctx.progress((i + 1) / 10)
    if "crash" in path.name:
        os._exit(3)
    with open(os.environ["SPINDLE_UI_LOG"], "a") as fh:
        fh.write(f"{option}|{path.name}|{os.getpid()}\n")

def record_pdf(path, option, ctx): record(path, "pdf:" + option, ctx)
def record_image(path, option, ctx): record(path, "image:" + option, ctx)
