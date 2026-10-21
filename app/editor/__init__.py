"""The editor: Crop / Edit (and in later steps Annotate / Redact / Metadata)
for one image or PDF.

It runs as its own process (`main.py --editor <tool> <file>`), started by
the wheel when a file is dropped on an editor wedge, and exits when its
window closes. The resident wheel process therefore never loads PyMuPDF,
numpy or the editor's QML, and its idle memory doesn't change.

    state.py     the edit state (plain dicts) and the undo history
    imaging.py   pixel math shared by the preview and the saved file
    document.py  opening a file, rendering previews, saving the result
    provider.py  image provider: page renders / thumbnails / previews for QML
    bridge.py    the QObject QML talks to (`editor`)
    app.py       process entry point: window, wheel handshake
    launcher.py  wheel side: start the editor process (no heavy imports)
"""
