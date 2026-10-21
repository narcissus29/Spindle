# UI suites

Scripted runs of the real wheel (and editor) windows. They are not part of
`pytest`: they open windows, and the `real_*` ones move your real pointer.
Run them from the project root:

```bash
.venv/bin/python tests/ui/suite_wheel.py         # close rules, park, batch, pin
.venv/bin/python tests/ui/suite_conversions.py   # helper process, progress, cancel, results
.venv/bin/python tests/ui/suite_move.py          # dragging a pinned wheel, snapping
.venv/bin/python tests/ui/suite_dropzone.py      # shortcut-first drop zone, combined PDFs
.venv/bin/python tests/ui/suite_editor_flow.py   # wheel -> editor process handshake
.venv/bin/python tests/ui/suite_target.py        # Compress to a size: target ring, Custom, batches
```

Each prints `PASS` / `FAIL` lines and ends with `ALL PASSED` or `FAILED: [...]`.
Prefix `QT_QPA_PLATFORM=offscreen` to run them without a display (the
`suite_*` ones). Output files go to a fresh temporary folder, or to `$S`.

## Editor canvas on the GPU

`tests/test_editor_canvas.py` is part of pytest (offscreen, software
renderer). Some rendering problems only show on the GPU renderer, so run it
there as well before a release:

```bash
QT_QPA_PLATFORM=wayland .venv/bin/python -m pytest tests/test_editor_canvas.py
```

## Editor screenshots

```bash
.venv/bin/python tests/ui/editor_shots.py <file> <out-prefix> <script.py> [tool] [software]
```

Opens the editor on `<file>` and runs `<script.py>`, a list of timed
steps (`@step(ms)`) that can drive the window (QTest), call the `bridge`
and save screenshots (`shot("name")`). See the docstring for what a script
can use.

## Real input (GNOME on Wayland only)

```bash
.venv/bin/python tests/ui/real_pin.py    # pin / drop zone: clicks outside reach the window below
.venv/bin/python tests/ui/real_move.py   # drag a pinned wheel by its rim with the real pointer
.venv/bin/python tests/ui/real_target.py # Compress > Custom: the real keyboard reaches the size field
```

These drive the real pointer through Mutter's RemoteDesktop D-Bus API
(GNOME may ask once for permission). They first open a maximized window
of their own underneath, calibrate the pointer against it, and abort if it
doesn't line up, so every injected click lands on one of their own windows.
Don't touch the mouse while they run (about a minute).

All suites keep their settings in `~/.config/spindle-test`; delete it
afterwards.
