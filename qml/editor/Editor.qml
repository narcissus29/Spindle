import QtQuick
import QtQuick.Window
import "."

// The editor window: tools on the left, the canvas in the middle, the
// tool's options on the right, page thumbnails below (PDFs).
Window {
    id: win

    width: 1240
    height: 820
    minimumWidth: 860
    minimumHeight: 560
    visible: true
    color: Style.windowBg
    title: editor.fileName + (editor.modified ? " (edited)" : "") + " — Spindle"

    property bool closeConfirmed: false
    readonly property bool modal: saveSheet.shown || confirm.shown || textSheet.shown
    // Typing on the canvas or in a text field: Esc and the one-key
    // shortcuts belong to the text then.
    readonly property bool typing: view.marksLayer.editing
                                   || (activeFocusItem !== null && activeFocusItem.cursorPosition !== undefined)

    // Color values while a slider is dragged (the canvas previews them);
    // otherwise they follow the saved state.
    QtObject {
        id: live
        property real brightness: editor.brightness
        property real contrast: editor.contrast
        property real saturation: editor.saturation
    }

    onClosing: (close) => {
        if (editor.saving) {
            close.accepted = false
            toast.show("Saving… the window closes when it's done")
            saveSheet.closeAfter = true
            return
        }
        if (editor.modified && !closeConfirmed) {
            close.accepted = false
            confirm.open()
        }
    }

    function openSave(closeAfter) {
        saveSheet.closeAfter = !!closeAfter
        saveSheet.open()
    }

    Item {
        id: root
        anchors.fill: parent
        focus: !win.modal

        // Space held: drag pans, also while cropping.
        Keys.onPressed: (e) => { if (e.key === Qt.Key_Space && !e.isAutoRepeat) { view.spaceHeld = true; e.accepted = true } }
        Keys.onReleased: (e) => { if (e.key === Qt.Key_Space && !e.isAutoRepeat) { view.spaceHeld = false; e.accepted = true } }

        TopBar {
            id: top
            anchors.left: parent.left
            anchors.right: parent.right
            onSaveClicked: win.openSave(false)
        }

        ToolRail {
            id: rail
            anchors.left: parent.left
            anchors.top: top.bottom
            anchors.bottom: parent.bottom
        }

        SidePanel {
            id: side
            anchors.right: parent.right
            anchors.top: top.bottom
            anchors.bottom: parent.bottom
            anchors.rightMargin: 14
            anchors.bottomMargin: 14
            width: 300
            vp: view
            live: live
            onViewRequested: (key) => {
                textSheet.heading = "XMP metadata"
                textSheet.body = editor.metaXmp()
                textSheet.open()
            }
        }

        Rectangle {  // canvas card
            id: canvas
            anchors.left: rail.right
            anchors.right: side.left
            anchors.top: top.bottom
            anchors.bottom: strip.top
            anchors.rightMargin: 14
            anchors.bottomMargin: editor.isPdf ? 8 : 14
            radius: Style.radius + 2
            color: Style.canvasBg
            border.width: 1
            border.color: Style.canvasEdge
            clip: true

            Viewport {
                id: view
                objectName: "view"
                anchors.fill: parent
                live: live
            }

            ZoomBar {
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 12
                vp: view
            }
        }

        PageStrip {
            id: strip
            visible: editor.isPdf
            anchors.left: rail.right
            anchors.right: side.left
            anchors.bottom: parent.bottom
            anchors.rightMargin: 14
            anchors.bottomMargin: editor.isPdf ? 10 : 0
            height: editor.isPdf ? 112 : 0
        }

        Toast {
            id: toast
            anchors.horizontalCenter: canvas.horizontalCenter
            anchors.bottom: canvas.bottom
            anchors.bottomMargin: 64
            onActionClicked: editor.showInFolder()
        }

        SaveSheet {
            id: saveSheet
            objectName: "saveSheet"
            onSaveRequested: editor.save(saveSheet.flatten, saveSheet.keepLocation)
        }

        TextSheet { id: textSheet }

        ConfirmSheet {
            id: confirm
            onDiscard: { win.closeConfirmed = true; win.close() }
            onSaveFirst: win.openSave(true)
        }
    }

    // Typing finished: the window's keys (Space to pan, shortcuts) again.
    Connections {
        target: view.marksLayer
        function onEditingChanged() { if (!view.marksLayer.editing) root.forceActiveFocus() }
    }
    // Leaving Annotate while typing keeps what was typed.
    Connections {
        target: editor
        function onChanged() { if (editor.tool !== "annotate" && view.marksLayer.editing) view.marksLayer.commitText() }
    }

    Connections {
        target: editor
        function onSaved(name) {
            saveSheet.close()
            toast.show("Saved as " + name + (editor.lastSaveNote !== "" ? "  ·  " + editor.lastSaveNote : ""), "Show in folder")
            if (saveSheet.closeAfter) {
                win.closeConfirmed = true
                win.close()
            }
        }
        function onSaveFailed(message) {
            saveSheet.closeAfter = false
            toast.show("Couldn't save: " + message, "", true)
        }
    }

    // ---- keyboard ----

    Shortcut { sequences: [StandardKey.Undo]; enabled: !win.modal; onActivated: editor.undo() }
    Shortcut { sequences: [StandardKey.Redo, "Ctrl+Y"]; enabled: !win.modal; onActivated: editor.redo() }
    Shortcut { sequences: [StandardKey.Save]; enabled: !win.modal; onActivated: win.openSave(false) }
    Shortcut { sequence: "Ctrl+1"; enabled: !win.modal; onActivated: editor.setTool("crop") }
    Shortcut { sequence: "Ctrl+2"; enabled: !win.modal; onActivated: editor.setTool("edit") }
    Shortcut { sequence: "Ctrl+3"; enabled: !win.modal; onActivated: editor.setTool("annotate") }
    Shortcut { sequence: "Ctrl+4"; enabled: !win.modal; onActivated: editor.setTool("redact") }
    Shortcut { sequence: "Ctrl+5"; enabled: !win.modal; onActivated: editor.setTool("metadata") }
    Shortcut { sequence: "Ctrl+R"; enabled: !win.modal; onActivated: editor.rotate(1) }
    Shortcut { sequence: "Ctrl+Shift+R"; enabled: !win.modal; onActivated: editor.rotate(-1) }
    Shortcut { sequences: ["Return", "Enter"]; enabled: !win.modal && editor.tool === "crop"; onActivated: editor.setTool("edit") }
    Shortcut { sequences: ["Del"]; enabled: !win.modal && editor.isPdf && editor.tool === "edit"; onActivated: editor.deletePage() }
    Shortcut { sequences: [StandardKey.ZoomIn, "Ctrl+="]; enabled: !win.modal; onActivated: view.zoomIn() }
    Shortcut { sequences: [StandardKey.ZoomOut]; enabled: !win.modal; onActivated: view.zoomOut() }
    Shortcut { sequence: "Ctrl+0"; enabled: !win.modal; onActivated: view.actualSize() }
    Shortcut { sequence: "F"; enabled: !win.modal; onActivated: view.fit() }
    Shortcut { sequences: [StandardKey.MoveToPreviousPage]; enabled: !win.modal; onActivated: editor.goToPage(editor.page - 1) }
    Shortcut { sequences: [StandardKey.MoveToNextPage]; enabled: !win.modal; onActivated: editor.goToPage(editor.page + 1) }
    Shortcut { sequence: "Home"; enabled: !win.modal && editor.isPdf; onActivated: editor.goToPage(0) }
    Shortcut { sequence: "End"; enabled: !win.modal && editor.isPdf; onActivated: editor.goToPage(editor.pageCount - 1) }
    Shortcut { sequence: "Esc"; enabled: !win.modal && !win.typing; onActivated: win.close() }

    // Annotate: tool keys, and Delete for the selected mark / redaction box.
    readonly property bool annotating: editor.tool === "annotate" && !win.modal && !win.typing
    Shortcut { sequence: "V"; enabled: win.annotating; onActivated: editor.setAnnotateTool("select") }
    Shortcut { sequence: "P"; enabled: win.annotating; onActivated: editor.setAnnotateTool("pen") }
    Shortcut { sequence: "H"; enabled: win.annotating; onActivated: editor.setAnnotateTool("highlight") }
    Shortcut { sequence: "T"; enabled: win.annotating; onActivated: editor.setAnnotateTool("text") }
    Shortcut { sequence: "A"; enabled: win.annotating; onActivated: editor.setAnnotateTool("arrow") }
    Shortcut { sequence: "R"; enabled: win.annotating; onActivated: editor.setAnnotateTool("rect") }
    Shortcut {
        sequences: ["Del", "Backspace"]
        enabled: !win.modal && !win.typing && ((editor.tool === "annotate" && editor.selectedMark >= 0)
                                              || (editor.tool === "redact" && view.marksLayer.selectedBox >= 0))
        onActivated: {
            if (editor.tool === "annotate") {
                editor.deleteMark(editor.selectedMark)
            } else {
                editor.deleteRedaction(view.marksLayer.selectedBox)
                view.marksLayer.selectedBox = -1
            }
        }
    }
}
