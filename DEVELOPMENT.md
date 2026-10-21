# Spindle: development and reference

For users, [README.md](README.md) is all there is to know. This file is for
building and working on Spindle, and has the full guide to every feature.

Drag a file onto a radial wheel and drop it on a wedge to convert or edit it.
Open source, cross-platform (Linux and Windows), inspired by the macOS app
*Tangerine*.

- **Convert wheel**: output formats for the dropped file
  (PDF → DOCX, TXT, JPG, PNG; images → other image formats + PDF; Word /
  Excel / PowerPoint → PDF). Several files: **PDF** makes one PDF each,
  **Merge** one combined PDF from any mix.
- **Actions wheel**: Compress, Metadata, Edit, Annotate, Add BG, Crop, Redact.
- PDFs open on Convert, images on Actions. Drop on a wedge to run it right
  away, or drop on the **center** to park the file and pick at leisure.
- Drop **many files at once** to run an option on all of them.
- Reads PDF, JPG, PNG, WEBP, BMP, GIF, TIFF and **HEIC / HEIF** (iPhone
  photos). HEIC is only read: whatever is made from one is a JPG (or the
  format picked in Convert), upright and with its colors (Display P3) kept.
- **Pin** the wheel to keep it open while you drop files one after another.
- Press the shortcut **before** grabbing a file and the wheel waits as a
  **drop zone**: clicks elsewhere go through, so you can go and pick a file.

## Run from source

Python 3.11 (3.10+ works), Linux (Wayland or X11) or Windows 10/11.

```bash
python3 -m venv .venv                  # Ubuntu: sudo apt install python3-venv first if needed
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python main.py --show
```

On Windows use `py -m venv .venv` and `.venv\Scripts\...`. On an X11
session you may need `sudo apt install libxcb-cursor0`.

The first start opens the welcome window (shortcut, start at login). To see
it again without losing your settings: `main.py --welcome` (also works with
the AppImage / Spindle.exe; add `--installed` to show the AppImage install
note). Settings: `main.py --settings`.

Command line:

| | |
|---|---|
| `main.py` | start Spindle (hidden), or show the wheel if it runs already |
| `--show`, `--toggle`, `--hide`, `--quit` | control the running Spindle |
| `--background` | start hidden (what start at login runs): never shows the wheel, does nothing if Spindle already runs |
| `--settings`, `--welcome` | the settings / welcome window |
| `--stats` | log RAM / CPU / FPS every few seconds |
| `--software` | software rendering for this run |
| `--selftest` | check and measure this build (see Building), then exit |

### The keyboard shortcut from source

The welcome and Settings set the shortcut: on Windows Spindle registers it
itself; on GNOME it is written with `gsettings` as a custom shortcut. From a
source checkout that shortcut runs `python main.py --toggle` (about half a
second); the AppImage uses a D-Bus call instead (about 16 ms). On other
desktops, bind the command Settings shows as a custom shortcut.

## Building

```bash
.venv/bin/pip install -r requirements.txt pyinstaller
.venv/bin/python packaging/build.py
```

- **Linux:** `dist/Spindle-x86_64.AppImage`. PyInstaller makes one folder
  (fast start: a one-file build would unpack itself every time), then
  appimagetool packs it with the static runtime, so users don't need
  libfuse2. Build on the oldest Linux you want to support (CI uses Ubuntu
  22.04).
- **Windows:** `dist/Spindle-Setup.exe`, made with Inno Setup 6 (`ISCC`
  must be installed): a per-user install with no admin prompt.
- `--folder` stops after PyInstaller (`build/dist/...`).
- `spindle.spec` leaves out the Qt parts Spindle doesn't use (3D,
  Multimedia and its FFmpeg, WebEngine, Pdf, Controls, translations, the
  GTK theme plugin and the system libraries only it needed).

**Self-test:** `Spindle --selftest` (any build, also offscreen:
`QT_QPA_PLATFORM=offscreen`) starts the app with its own socket and config,
measures the idle wheel, runs PDF → DOCX and a 12 MP photo → under 200 KB in
the helper, opens the editor, and prints one `SELFTEST {...}` line with the
memory figures and `"ok": true`.

**AppImage behavior:** on first run it copies itself to
`~/Applications/Spindle.AppImage` and runs from there; every start rewrites
the app-menu entry, icon, D-Bus service file and (if on) autostart for that
path. Settings > Remove Spindle undoes all of it.

### Releases

`.github/workflows/build.yml` runs by hand (Actions > Build > Run
workflow) or on a `v*` tag. Both build, self-test (Windows: after a silent
install of the real installer, which is then uninstalled again) and record
sizes. A tag creates a **draft** release with `Spindle-Setup.exe` and
`Spindle-x86_64.AppImage`; publishing it makes the README's download links
(`releases/latest/download/...`) work. The repository has to be public for
people to download without a GitHub account.

## Installing

- **Windows 10 / 11:** open `Spindle-Setup.exe`. If Windows says "Windows
  protected your PC", click **More info** → **Run anyway** (Spindle isn't
  code-signed yet). Per-user install, no administrator rights.
- **Linux** (Ubuntu 22.04 or newer, and similar): right-click
  `Spindle-x86_64.AppImage` → **Properties** → turn on **Executable as
  Program**, then double-click it. It copies itself to `~/Applications` and
  adds itself to the app menu; Settings > Remove Spindle takes it out again.

## Using it

The app stays resident in the background (about 0% CPU while hidden), with
a tray icon (Open, Open and pin, Settings, Quit). See "Run from source" for
the command line.

To use it, start dragging one or more files in your file manager, press the
shortcut while still holding them, and move them onto the wheel.

Two ways to drop:

- **On a wedge:** runs that option right away.
- **On the center (park):** the files stay in the middle of the wheel (a
  thumbnail of the first image, or the first page of a PDF, stacked with a
  count badge for several files) and the wheel stays open. Scroll (mouse
  wheel or touchpad) or press **Tab** to switch between Convert and Actions,
  then click a wedge to run it.
- **More files onto parked ones:** they are added to the stack (files
  already on it are skipped) and the wedges show what works for all of
  them. Dropped on the center they wait with the others; dropped on a
  wedge, that option runs on the whole stack. The small **×** on the stack
  puts the files away; closing the wheel (Esc, clicking away) does too.

### While it runs

- The center shows progress: a ring around it fills with the current
  file's progress (it spins while that can't be told yet, e.g. while a PDF
  is being analysed), and the pill says what is happening: "Page 12/60" or
  "42%" for one file, "File 2/3 · 20%" for several.
  Then it shows "Done" (or "2 failed") for a moment and the wheel closes.
- **Esc** (or clicking away) only hides the wheel. The conversion keeps
  going, and a desktop notification tells you when it's finished.
- **Cancel:** hover the center while it runs. It turns red and says
  "Cancel"; click it to stop. Files not yet finished are left untouched, and
  nothing half-written is left behind.

### Where the results go

Next to the original file, never overwriting anything:

- `report.pdf` → `report.docx` (or `report (1).docx` if that name is taken)
- A multi-page PDF → JPG/PNG goes into a folder: `report (PNG)/page-001.png`, ...
- Photos keep their EXIF rotation. Transparent areas become white in JPG
  and BMP.
- A multi-page TIFF → PDF gets every page. To other image formats, and in
  Compress and Add BG, multi-page TIFFs and animated GIF / WEBP / PNG are
  refused with a reason ("Multi-page TIFF: convert to PDF to keep every
  page", "Animated GIF not supported") instead of silently keeping only the
  first frame.
- Images put into a PDF (one or combined) never carry their metadata:
  EXIF with GPS location and camera details, XMP, comments and a motion
  photo's video are cut out of the embedded image. This is lossless: the
  photo's compressed data goes in byte for byte.
- PDF → JPG/PNG renders at 150 DPI (`pdf_image_dpi`), and JPG/WEBP use
  quality 90 (`jpeg_quality`).

### Actions

- **Compress** writes `report (compressed).pdf` / `photo (compressed).jpg`,
  and the center shows the saving ("−62%"). How hard it squeezes depends on
  `compress_preset`:
  - `light`: lossless steps only. PDFs get their fonts trimmed to the
    characters used and their structure cleaned. PNGs get maximum
    compression, TIFFs LZW. JPG and WEBP are left alone.
  - `balanced` (default): adds JPEG quality 75 for photos, WEBP 80, and
    re-encodes JPEG photos inside PDFs (downsampled above 200 DPI).
    Screenshots and diagrams in PDFs stay crisp.
  - `strong`: every image in a PDF at quality 60 (above 120 DPI down to
    100), JPG 60, WEBP 65, and images larger than 2560 px are scaled down.

  BMPs become PNGs. Rotated phone photos come out upright. If a file
  wouldn't get at least 5% smaller, nothing is written and the center says
  "Already compact".

  **Compress to a size** (for upload forms that say "max 50 KB"): drop the
  file on the center to park it, then click **Compress**. The wedges turn
  into **Auto** (the preset above), **20 KB, 50 KB, 100 KB, 200 KB, 500 KB,
  1 MB** and **Custom** (type a number; Tab or the KB / MB chip switches the
  unit). Esc, a right-click, scrolling or a click on the center goes back.
  - The copy is named `photo (50 KB).jpg` and is at most that size (1 KB =
    1000 bytes, so it also passes forms that count 1024), as close to it as
    possible. The center says "48 KB ✓".
  - Photos: the highest quality that fits; if that isn't enough the picture
    is made smaller too. PNG, BMP, TIFF and GIF come out as JPG (transparent
    areas white); WEBP stays WEBP. Metadata is left out (it takes space).
  - PDFs: images are downsampled and recompressed step by step. A scanned
    PDF (no text on any page) may have its pages saved as pictures as a
    last step; PDFs with real text never are.
  - If the size can't be reached, the smallest possible copy is still
    written and the center says "Smallest: 340 KB" in amber, never a tick.
  - Several parked files: each one is fitted ("3 of 3 under 50 KB ✓").
  - A file already under the size is left alone ("Already 32 KB ✓").
- **Metadata** on **one file** opens the editor's **Info** viewer (see
  below): see what the file carries, change or remove single entries, or
  press **Remove all**. On **several files** it removes everything
  silently from each, writing `photo (clean).jpg` / `report (clean).pdf`.
  Pixels and pages are not touched:
  - JPEG: EXIF (GPS location, camera, dates), XMP, IPTC and comments are
    cut out of the file. The photo itself isn't re-compressed, and its color
    profile and orientation are kept.
  - PNG: text and time chunks are removed. WEBP: EXIF and XMP chunks.
  - TIFF: re-saved losslessly without metadata. Multi-page TIFFs are
    refused ("Multi-page TIFF not supported"), so no page is ever lost.
  - PDF: document info (author, creator app, dates), XMP metadata (the
    document's and any on pages or images), attachments, JavaScript, page
    thumbnails and private app data (Illustrator keeps the whole working
    file there). Comments keep their text but lose author names and dates.
    **Photos inside the PDF** are cleaned like JPEG files (EXIF with GPS,
    XMP, IPTC, comments), byte for byte, without re-encoding. Earlier
    versions left in the file by incremental saves (which can still hold
    the old author) are dropped: the PDF is always written out fresh.
  - Anything stored after the end of the image is removed too: the video
    of a motion photo (which can carry its own GPS location), extra
    preview images, or data other tools appended. The result is a plain
    still photo, and the notification says "Motion photo data removed".

  Files with nothing to remove are skipped ("No metadata").
- **Add BG** (images only) fills transparent areas with `background_color`
  (white by default) and writes `logo (bg).png`. Images without any
  transparency are refused ("No transparency"), and nothing is written.

### The editor (Crop, Edit, Annotate, Redact, Metadata)

These wedges open an editor window for one file (Crop, Edit, Annotate and
Redact are left off the wheel when you drop several files; Metadata then
cleans them silently). The center says "Opening…" for about
half a second, then the window appears and the wheel closes. If the file
can't be edited, the reason shows in the center instead ("Password-protected
PDF", "Multi-page TIFF not supported").

- **Tools** on the left: Crop, Adjust (Pages for PDFs), Annotate, Redact,
  Info. Switch any time; one undo history covers them all.
- **Crop:** drag the corners or edges, drag inside to move, or drag on the
  page to start a new rectangle. Presets: Free, Original, 1:1, 4:3, 16:9
  (with a portrait / landscape switch). For PDFs the crop applies to all
  pages unless you turn that off.
  - A PDF crop only hides the rest of the page: the content is still in the
    file. Use Redact to remove it.
  - **Exact size** (images): type the width × height in pixels a form asks
    for (a 200 × 230 photo, a 140 × 60 signature). The crop box keeps that
    shape while you move it over the face; the copy is exactly that size
    (`photo (200x230).jpg`). The panel warns if it has to enlarge.
- **Adjust (images):** rotate, flip, brightness, contrast and saturation,
  previewed live. The saved file uses exactly the preview's math.
- **Pages (PDFs):** rotate the page on screen (or all pages), and delete or
  restore pages.
- **Annotate:** pen, highlighter, text, arrow and box, with 8 colors plus a
  color picker and 4 thicknesses (text sizes). Marks stay on the page (or
  inside the crop): nothing starts off it, boxes, arrows and moved marks
  stop at its edge, text wraps there, and anything running past it is cut
  off, on screen exactly as in the saved file. **Select** to click a mark,
  drag to move it, Delete to remove it; double-click text to edit it, or
  pick a color to recolor the selected mark.
  - PDFs: saved as real PDF annotations, so other apps can still edit or
    remove them. Tick **Flatten annotations** when saving to make them part
    of the page instead. (Text outside Latin-1, e.g. Greek or Chinese,
    always goes into the page: PDF annotations can't show it.)
  - Images: drawn into the picture.
- **Redact:** drag boxes over what has to go. In PDFs, **Find text** lists
  every match with its context (match case and whole words optional, and a
  phrase that wraps onto the next line is found too); untick any you want
  to keep and press **Redact N matches**.
  - PDFs get **true redaction**: the text under a box is deleted from the
    file (not just covered), image pixels under it are blanked, and
    annotations, form fields and links touching it are removed. A scanned
    page has no text to search; boxes still black out its pixels.
  - Images: the boxes are filled solid black.
  - A redacted copy is always named `(redacted)` and saved without any
    metadata (PDFs: document info, XMP, attachments, scripts and page
    thumbnails go too, and old versions of objects are dropped).
  - Bookmarks are kept, but any text that was redacted (found by search
    or under a drawn box) is replaced by `[redacted]` in their titles.
    Pieces shorter than 3 characters, like an initial, only count as whole
    words: "R" is struck from "Report by R Sharma", but not from "Report".
  - The file name isn't redacted: rename the copy if the name itself is
    sensitive.
  - **Show as saved** previews the boxes in solid black.
  - Photos inside a redacted PDF lose their own metadata (EXIF, GPS) too.
- **Info:** everything the file carries besides the picture or pages,
  with a prominent **Remove all** (then **Save clean copy**: one more
  click, `photo (clean).jpg`).
  - Photos: location (shown as coordinates, editable as
    `48.8584, 2.2945`), description, artist, copyright, date taken, camera
    make and model are editable; every other EXIF entry (exposure, lens,
    serial numbers, maker notes, ...) and the embedded thumbnail (which can
    show what was cropped out), XMP (view the raw text), IPTC, comments,
    PNG text (e.g. prompts saved by image generators) and a motion photo's video can each be
    removed. The orientation and color profile are always kept: the photo
    needs them to look right.
  - Changing metadata never re-encodes the photo: the new metadata is
    swapped into the file as it is (JPEG, PNG, WEBP). Text keeps any
    characters ("Zoë"). TIFF can only be cleaned as a whole (re-saved
    without loss); GIF and BMP carry nothing to change.
  - PDFs: title, author, subject, keywords, the apps that made it and the
    dates are editable; XMP, the photos' metadata, comment authors,
    attached files, JavaScript, page thumbnails and app data can each be
    removed.
  - Every change is one undo step and is written when you save the copy.
- **Save copy** (Ctrl+S) writes a new file next to the original:
  `photo (cropped).jpg`, `(annotated)`, `(redacted)`, `(clean)` (all
  metadata removed, nothing else changed), or `(edited)`. The original is
  never touched, and a second save gets its own name. JPEGs are saved at
  quality 95.
  - An edited picture keeps the original's metadata, with your Info
    changes, turned upright and at the new size, but without the
    thumbnail or a motion photo's video (they show the old picture).
    **The location is left out** (also from XMP) unless you tick **Keep
    location** in the save sheet, shown when the photo has one, or set a
    location yourself in Info.
    Redacted copies carry no metadata at all; edited TIFFs carry none.
- **Limit file size** in the save sheet: type a size (KB or MB) and the copy
  is saved at the best quality that fits, made smaller if needed:
  `photo (200x230, 50 KB).jpg`. Images come out as JPG (WEBP stays WEBP)
  without metadata; for PDFs the images inside are made smaller step by
  step. If the size can't be reached, the smallest possible copy is saved
  and the message says so.
- Closing with unsaved edits asks first.

| Keys | |
|---|---|
| Ctrl+Z / Ctrl+Shift+Z or Ctrl+Y | Undo / redo |
| Ctrl+S | Save a copy |
| Ctrl+1 … Ctrl+5 | Crop, Adjust / Pages, Annotate, Redact, Info |
| Click a value, Enter / Esc | Info: edit it, keep / cancel the change |
| Ctrl+R / Ctrl+Shift+R | Rotate right / left |
| Enter | Finish cropping |
| Del | Delete the page (PDF, Pages tool), the selected mark (Annotate) or box (Redact) |
| V / P / H / T / A / R | Annotate: select, pen, highlighter, text, arrow, box |
| Enter / Shift+Enter | Text: finish / new line |
| Mouse wheel, Ctrl+wheel, pinch | Zoom at the pointer |
| Ctrl++ / Ctrl+− / Ctrl+0 / F | Zoom in / out / 100% / fit |
| Space+drag, middle-drag, touchpad scroll | Pan |
| PgUp / PgDn, Home / End | Previous / next, first / last page |
| Esc | Close the editor |

The editor is a separate process that starts when you need it and exits
when you close it, so the always-running wheel stays small.

Conversions and actions run in a separate helper process. It starts with the first job
and exits after 30 s with nothing to do, so the wheel never stutters while a
big file converts, and idle memory stays low. The first DOCX conversion
after a pause takes about 2 s longer while the helper loads pdf2docx.

### Several files at once

Select many files and drag them together. The option runs on every file,
one after another, in the background, and the center shows progress
("File 2/3 · 20%") until the batch is done. A single file still runs after the wheel
closes, as before.

On Convert, several files always get the same two choices:

- **PDF**: one PDF per file (`photo1.pdf`, `report.pdf`, ...), wherever every
  file can become one (images, office documents, or both; files that are
  PDFs already have nothing to become).
- **Merge**: **one** PDF from all of them, named after the first file, with
  pages in the order your file manager lists the files:
  `photo1 (combined).pdf`. Any mix of PDFs, images and office documents:
  images become pages sized to them (every page of a multi-page TIFF), PDFs
  keep their bookmarks, still pointing at the right pages.

If one of the files can't be used (a password-protected PDF, an animated
GIF), nothing is written and the reason names that file.

With a mix of types, the wheel only offers options that work for all of
them. A PDF plus a PNG, for example, gets all of Actions but only JPG and Merge on
Convert. If no option fits every file, the center says **Mixed files** and
the drop is refused.

### Office documents (Word, Excel, PowerPoint)

Word (`.docx .doc .docm .rtf .odt`), Excel (`.xlsx .xls .xlsm .ods`) and
PowerPoint (`.pptx .ppt .pptm .odp`) files open on Convert with **PDF**
(and **Merge** with several files). Spindle doesn't bundle an office
suite; it uses the one you have:

- **Windows:** Microsoft Word / Excel / PowerPoint if installed, else
  LibreOffice.
- **Linux:** LibreOffice (apt, Snap or Flatpak). On Ubuntu 22.04 the
  `libreoffice-impress-nogui` package can't open presentations; install
  `libreoffice-impress`.
- Neither: the center says **Needs Word or LibreOffice** (Excel /
  PowerPoint for those files).

The file is opened read-only with macros forced off, no dialogs, and not
added to the app's recent files; the original is never changed. A
password-protected file fails at once ("Password-protected document")
instead of waiting on a hidden password prompt. An app that stops
answering for 5 minutes is stopped ("Word didn't respond"), and Cancel
stops the Word or LibreOffice that Spindle started. Spindle starts its own
hidden Word / Excel, keeps it for the rest of a batch and closes it after;
documents you have open are never touched. PowerPoint runs once per user:
if yours is open, Spindle uses it and leaves it open.

The ring spins while the office app works (it doesn't report pages).

### Shortcut first: the drop zone

Press the shortcut with nothing in hand and the wheel opens as a **drop
zone**: only the wheel itself takes clicks, so you can click around, open
folders in your file manager and drag a file onto it. It shows the **×**,
and it stays open when you click elsewhere or it loses focus. It closes
after one completed action, or with **×**, **Esc** (when it has focus) or
the shortcut again. Pin works on top of it as usual.

Press the shortcut while you're already dragging a file and you get the
usual pop-up wheel instead (it closes on a click outside, on focus loss,
or when you drop outside it). On Windows and X11 Spindle checks whether the
mouse button is down. Wayland doesn't let apps see that, so there the wheel
opens as a pop-up and becomes a drop zone if no drag reaches it within
about half a second.

### Pin mode

Click the **pin** on the wheel's rim (top right) to keep the wheel open:

- It stays open after each action, showing progress and then "Done".
- Clicks outside the wheel pass through to the desktop and other apps, so
  you can grab more files and drop them one by one. Losing focus doesn't
  close it.
- Close it with the **×** next to the pin, **Esc** (when the wheel has focus)
  or the shortcut. Every new wheel starts unpinned.
- **Move it:** drag a pinned wheel by its rim (the outer edge, where the
  pointer turns into a hand). When you let go, it glides to the nearest
  screen edge. That spot is remembered, and the next time you pin, the
  wheel moves there. An unpinned wheel always opens centered (at the cursor
  where the platform allows it).

A pinned wheel has a filled pin and a soft glow around the rim.

> **Tip:** pin the wheel and drag it to the right edge of the screen, then
> put your file manager on the left half. You can then keep dragging files
> across without the file manager ever covering the wheel.

The pop-up wheel hides on **Esc**, on the shortcut again, after a wedge runs,
when you click outside it, when it loses focus, or when you drop a file
outside it. The only exception is while a file is being dragged over the wheel. A
parked file waits until you pick a wedge or cancel. (During a drag the file
manager keeps the keyboard and scroll wheel, which is why switching works on
a parked file.)

On Wayland, Esc may need one click on the wheel first: a drop doesn't move
keyboard focus away from the file manager, and Wayland doesn't let apps take
it. Clicking outside the wheel always works.

## Configuration

A JSON file is created on first run:

- Linux: `~/.config/spindle/config.json`
- Windows: `%LOCALAPPDATA%\spindle\config.json`

| Key | Default | Meaning |
|---|---|---|
| `theme` | `"blue"` | `blue` (macOS selection blue) or `orange` (warm peach) |
| `reduce_animations` | `false` | Turn off almost all motion |
| `renderer` | `"auto"` | `auto`, `software`, `opengl`, `d3d11` or `vulkan`. `auto` picks software when no GPU is found, and switches to it automatically if the GPU backend fails |
| `wheel_size` | `380` | Wheel diameter in logical pixels |
| `hotkey` | `"Alt+Meta+S"` = Win + Alt + S (Windows), `"Ctrl+Alt+Space"` (Linux) | The shortcut (Windows: registered by Spindle; Linux: set in GNOME by the welcome / Settings). Only the welcome / Settings window writes it; the wheel just tries it |
| `setup_done` | `false` | The first-run welcome was completed |
| `tray_icon` | `true` | Icon in the system tray / top bar |
| `compress_custom` | `""` | The last size typed in Compress > Custom |
| `low_memory_mode` | `false` | Free GPU resources while hidden (less RAM, slower first frame) |
| `log_stats` | `false` | Same as `--stats` |
| `pdf_image_dpi` | `150` | Resolution for PDF → JPG / PNG (36–600) |
| `jpeg_quality` | `90` | Quality for JPG and WEBP output (1–100) |
| `compress_preset` | `"balanced"` | `light`, `balanced` or `strong` (see Actions) |
| `background_color` | `"#ffffff"` | Add BG color, as `#rrggbb` |
| `pinned_x`, `pinned_y` | `-1` | Where a pinned wheel goes, as fractions of the screen (set by dragging it; `-1` = not set) |

## The default shortcut on Windows

**Win + Alt + S.** Picked by testing real keystrokes on Windows with two
input languages installed (English and English (India)):

- **Alt + Shift + Space** switched the keyboard language when Alt and
  Shift were let go before Space (Left Alt + Shift is Windows' language
  switch, the usual setup with English + Hindi / Punjabi).
- **Ctrl + Shift** can be the keyboard-layout switch; **Ctrl + Alt +
  Space** is taken by other apps (the Claude desktop app);
  **Ctrl + Alt + a letter** is AltGr + that letter, which types a
  character on many keyboards (₹ is AltGr + 4 on English (India)).
- **Win + Alt + S** worked in every press and release order, never
  switched the language and never opened Start.

The welcome and Settings show a note (and offer Win + Alt + S) when the
shortcut in use contains Alt + Shift or Ctrl + Shift.

## Coming from Satsuma

Spindle was called **Satsuma** up to 0.1.0-rc3. On its first start,
Spindle:

- asks a Satsuma that is still running to quit;
- copies its settings (`satsuma/config.json`: your shortcut, theme, ...)
  to Spindle's folder;
- removes what Satsuma set up, so nothing runs twice: its start at login
  (logon task, Run value, autostart file), its GNOME shortcut, app-menu
  entry, D-Bus file and `~/Applications/Satsuma.AppImage`, and its config,
  cache and log folders. What was on (start at login, the GNOME shortcut)
  is set up again for Spindle.

On Windows, installing Spindle over Satsuma replaces it: same entry in
Settings > Apps (now named Spindle), Satsuma's program folder, Start Menu
folder and desktop shortcut are removed.

## Start at login

"Start Spindle when I log in" runs `Spindle --background`, which never
shows the wheel (also not the welcome) and quietly exits if Spindle is
already running, for example because you opened it before the login
start got to it.

- **Windows:** a Task Scheduler task with a logon trigger, for your user
  only, unelevated ("Spindle (<user>)" in Task Scheduler). Windows starts
  programs from the Run registry key late after sign-in, often a minute or
  more; a logon task starts right away. It also runs on battery and has no
  time limit. If a policy forbids making the task, the Run key is used.
  The uninstaller removes it.
- **Linux:** `~/.config/autostart/spindle.desktop`.

The log (below) gets one line per start, e.g. `[startup] ready 0.9 s after
Python started, 1.6 s after the process was created; signed in 4.2 s ago;
booted 31.0 s ago (login start, autostart: task)`: if a login start is
slow, it tells whether Windows started Spindle late or Spindle itself was
slow.

## Logs

Every Spindle process (the wheel, the helper that converts, the editor,
the settings window) writes what it does and every error to one file:

- Windows: `%LOCALAPPDATA%\spindle\spindle.log`
- Linux: `~/.local/state/spindle/spindle.log`

Each line has the time and the process (`wheel`, `helper`, `editor`,
`settings`). At 1 MB it is renamed `spindle.log.1` (three old files are
kept). A hard crash inside a C library leaves its stack in `crash.log`
next to it. **Open log folder** is in the tray menu and in Settings >
Troubleshooting.

If the helper can't start, dies while starting, or doesn't answer within
90 s, the files fail with "The helper didn't start" in the pill, and the
log says why. If it dies mid-file, that file fails ("The helper stopped
unexpectedly") and the rest go to a fresh helper.

## Platform notes

- **Wayland:** apps can't place their own windows or read the global cursor
  position, so the wheel opens centered on the screen. It uses a transparent
  window that covers the screen while the wheel is open, so a click outside
  the wheel closes the wheel instead of reaching the app underneath. A
  pinned wheel or a drop zone only takes input inside its circle.
- **GNOME (Wayland) and click-through:** GNOME only picks up a change to
  which part of a window takes clicks when the window's size changes.
  Spindle resizes its overlay by one pixel and back whenever that changes
  (pin, unpin, drop zone, moving a pinned wheel). You may see the wheel
  shift by half a pixel for a moment.
- **GNOME (Wayland) and pin mode:** GNOME doesn't let apps keep a window on
  top. When you click another window, for example your file manager, GNOME
  raises it above the pinned wheel, and the wheel is hidden wherever the two
  overlap. Move the pinned wheel to a screen edge and keep the file manager
  on the other side (see the tip under Pin mode).
- **Windows:** notifications (a conversion that finishes after you close
  the wheel) come from the tray icon.
- **GNOME and the tray icon:** GNOME shows tray icons only with the
  AppIndicator extension (Ubuntu has it on). Without it, Settings is in the
  app grid (right-click Spindle).
- **Windows:** if the wheel shows a black square instead of a transparent
  background, set `"renderer": "opengl"` in the config.
- **Editor title bar on GNOME (Wayland):** GNOME leaves window decorations
  to the app; the editor uses Qt's Adwaita-style title bar. Set
  `QT_WAYLAND_DECORATION` to pick another one.
- **Software renderer:** the editor's live color preview is computed by the
  CPU on a screen-sized copy instead of the GPU, so it updates a little
  less smoothly on slow machines.
- **No GPU driver:** if `--stats` reports the `Software` backend on a machine
  that has a GPU, install its driver. On Ubuntu, `sudo ubuntu-drivers install`
  usually does it.

## Logo and icons

Pixel art, drawn by `assets/brand/make_brand.py` from the wheel's own
design (blue theme): the full logo (80 x 80 pixels, "SPINDLE" across the
lit top wedge) on a dark tile for the README, the welcome window, the
installer and GitHub's social preview (`social-preview.png`: upload it in
the repository's Settings > Social preview), and the app icon drawn
separately at 16, 24 and 32 px with an "S" in the hub. Larger sizes are
those drawings enlarged by whole numbers, and every size is its own image
(the .ico, the Linux icon theme, Qt), so nothing is ever blurred by
scaling.

## Project layout

```
main.py                 entry point, CLI, single-instance handoff
app/bridge.py           QObject exposed to QML (state, drag/drop, open/close)
app/window.py           frameless transparent QQuickView, placement, renderer
app/filetypes.py        file-type detection (extension + magic bytes)
app/handlers/           handler registry; pdf.py, image.py, combine.py (Convert);
                        compress.py, metadata.py, background.py (Actions)
app/editor/             the editor process: state.py (edits + undo), document.py
                        (open / render / save), imaging.py (pixel math), marks.py
                        (annotations + redaction), search.py, metadata.py (Info),
                        exif.py (EXIF read / write), containers.py (JPEG / PNG /
                        WEBP blocks), bridge.py (QML API), provider.py, app.py,
                        launcher.py
app/setup/              the welcome / settings window process (app.py)
app/tray.py             tray icon
app/heic.py             HEIC / HEIF reading (pi-heif)
app/selftest.py         `--selftest`: the build checks and measures itself
app/icons.py            SVG icon paths for QML
app/jobs/               helper process: process.py (UI side), runner.py (helper side)
app/outputs.py          collision-free output names, temp files
app/single_instance.py  QLocalServer / QLocalSocket + a lock file (one resident copy)
app/platform_utils.py   all OS-specific code (hotkey, GPU check, memory, autostart,
                        AppImage install, GNOME shortcut, D-Bus toggle, ...)
app/logs.py             the log file (every process), rotation, crash.log
app/stats.py            optional RAM / CPU / FPS logging
qml/                    the wheel UI (Qt Quick)
qml/editor/             the editor window (Qt Quick)
qml/setup/              welcome and settings windows (reuse qml/editor parts)
packaging/              PyInstaller spec, build.py, Inno Setup script, .desktop
.github/workflows/      CI: build, install, self-test, draft release
assets/icons/           24x24 stroke icons (path-only SVG)
assets/brand/           the logo and app icons (pixel art) and make_brand.py, which draws
                        them pixel by pixel: run it after changing the design
```

To add a real backend, point an entry in `app/handlers/__init__.py` at a
`"module:function"`. Handlers have the signature
`handler(path: Path, option: str, ctx: Context) -> None` (see
`app/handlers/common.py`) and run in the helper process, never in the UI.
Use `ctx.output_file(".ext")` / `ctx.output_dir("LABEL")` for where to write,
and `ctx.progress(0..1, "Page 3/12")` for progress (`ctx.progress(None,
"Analyzing…")` when it can't tell how far).

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

These cover the handlers, output naming, the helper protocol, cancel / crash
recovery, the helper's idle exit, and the editor: edit state and undo, PDF
crop / rotation placement (the saved file is compared with what the canvas
shows), saving, and loading its QML. They run offscreen, so no display is
needed.

`tests/ui/` holds scripted runs of the real windows (wheel rules, the helper
process, drop zone, combined PDFs, the editor handshake), and on GNOME,
tests that drive the real pointer. See [tests/ui/README.md](tests/ui/README.md).

## Roadmap

1. ✅ Wheel UI + drop
2. ✅ Conversions: PDF via PyMuPDF / pdf2docx, images via Qt
3. ✅ Compress / Metadata / Add BG
4. ✅ Shared editor: Crop, Adjust / Pages, Annotate, Redact, Info
5. ✅ Packaging: installer, AppImage, tray, welcome, settings (v0.1.0)
6. Next (v0.2): a small stand-in for OpenCV (about 42 MB less to download),
   with side-by-side DOCX comparison tests

## License

[AGPL-3.0](LICENSE): PyMuPDF, the PDF engine, is AGPL-licensed.
