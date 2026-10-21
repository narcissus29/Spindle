import QtQuick
import "."

PanelPage {
    id: panel

    required property Item vp

    tool: "crop"
    title: "Crop"
    subtitle: "Drag the corners or edges, drag inside to move, or drag on the page to start over."

    readonly property rect r: vp.overlay.r
    readonly property real cropW: r.width * vp.stageW
    readonly property real cropH: r.height * vp.stageH
    readonly property bool enlarging: editor.outputWidth > 0 && editor.outputWidth > Math.round(cropW) + 1
    readonly property string exactHint: {
        if (editor.outputWidth <= 0) return ""
        const from = Math.round(cropW) + " × " + Math.round(cropH) + " px"
        if (enlarging) return "Enlarged from " + from + ": it may look soft. Make the crop bigger if you can."
        return "Scaled down from the " + from + " crop."
    }

    Connections {  // undo / redo: the fields follow (unless being typed in)
        target: editor
        function onChanged() {
            if (!exactW.inputFocused) exactW.text = editor.outputWidth > 0 ? editor.outputWidth : ""
            if (!exactH.inputFocused) exactH.text = editor.outputHeight > 0 ? editor.outputHeight : ""
        }
    }

    function commitExact() {
        const w = parseInt(exactW.text), h = parseInt(exactH.text)
        if (w >= 16 && h >= 16 && (w !== editor.outputWidth || h !== editor.outputHeight)) {
            editor.setOutputSize(w, h)  // the crop takes that shape in the same step
        } else if (!(w >= 16 && h >= 16)) {  // not usable: show the size in use again
            exactW.text = editor.outputWidth
            exactH.text = editor.outputHeight
        }
    }
    readonly property string sizeText: {
        const w = r.width * vp.stageW, h = r.height * vp.stageH
        if (editor.outputWidth > 0)
            return editor.outputWidth + " × " + editor.outputHeight + " px"
        if (editor.isPdf)
            return Math.round(w * 25.4 / 72) + " × " + Math.round(h * 25.4 / 72) + " mm"
        return Math.round(w) + " × " + Math.round(h) + " px"
    }

    SectionLabel { text: "Aspect ratio" }

    Flow {
        width: parent.width
        spacing: 6
        Repeater {
            model: [
                { key: "free", label: "Free" }, { key: "original", label: "Original" },
                { key: "1:1", label: "1:1" }, { key: "4:3", label: "4:3" }, { key: "16:9", label: "16:9" },
            ]
            Chip {
                required property var modelData
                text: modelData.label
                checked: panel.vp.aspect === modelData.key
                onClicked: {
                    if (editor.outputWidth > 0)
                        editor.setOutputSize(0, 0)  // leaving Exact size
                    panel.vp.aspect = modelData.key
                    panel.vp.overlay.applyAspect()
                }
            }
        }
        Chip {
            visible: !editor.isPdf
            text: "Exact size"
            checked: panel.vp.aspect === "exact"
            onClicked: {
                if (panel.vp.aspect === "exact")
                    return
                panel.vp.aspect = "exact"
                // start from the crop as it is, in whole pixels
                const w = Math.max(16, Math.round(panel.r.width * panel.vp.stageW))
                const h = Math.max(16, Math.round(panel.r.height * panel.vp.stageH))
                editor.setOutputSize(w, h)
                exactW.focusInput()
                exactW.selectAll()
            }
        }
        IconButton {
            size: 30
            iconSize: 17
            icon: "orientation"
            tip: panel.vp.aspect === "exact" ? "Swap width and height"
               : panel.vp.portrait ? "Portrait (click for landscape)" : "Landscape (click for portrait)"
            enabled: panel.vp.aspect !== "free" && panel.vp.aspect !== "1:1"
            checked: panel.vp.aspect === "exact" ? editor.outputHeight > editor.outputWidth : panel.vp.portrait
            onClicked: {
                if (panel.vp.aspect === "exact") {
                    editor.setOutputSize(editor.outputHeight, editor.outputWidth)  // re-fits the crop too
                } else {
                    panel.vp.portrait = !panel.vp.portrait
                    panel.vp.overlay.applyAspect()
                }
            }
        }
    }

    // "Exact size": the copy is scaled to exactly W x H px, the crop keeps
    // that shape (form photos: 200 x 230, signatures: 140 x 60).
    Column {
        visible: panel.vp.aspect === "exact"
        width: parent.width
        spacing: 6
        Row {
            spacing: 6
            TextField {
                id: exactW
                objectName: "exactW"
                width: 84
                horizontalAlignment: TextInput.AlignRight
                validator: IntValidator { bottom: 1; top: 20000 }
                text: editor.outputWidth > 0 ? editor.outputWidth : ""
                placeholder: "Width"
                onAccepted: panel.commitExact()
                onInputFocusedChanged: if (!inputFocused) panel.commitExact()
            }
            Text { textFormat: Text.PlainText; anchors.verticalCenter: parent.verticalCenter; text: "×"; color: Style.inkSoft; font.pixelSize: Style.titleSize }
            TextField {
                id: exactH
                objectName: "exactH"
                width: 84
                horizontalAlignment: TextInput.AlignRight
                validator: IntValidator { bottom: 1; top: 20000 }
                text: editor.outputHeight > 0 ? editor.outputHeight : ""
                placeholder: "Height"
                onAccepted: panel.commitExact()
                onInputFocusedChanged: if (!inputFocused) panel.commitExact()
            }
            Text { textFormat: Text.PlainText; anchors.verticalCenter: parent.verticalCenter; text: "px"; color: Style.inkSoft; font.pixelSize: Style.textSize }
        }
        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            width: parent.width
            text: panel.exactHint
            color: panel.enlarging ? Style.danger : Style.inkSoft
            font.pixelSize: Style.smallSize
            wrapMode: Text.WordWrap
        }
    }

    Item { width: 1; height: 2 }
    SectionLabel { text: "Size" }
    Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        text: panel.sizeText
        color: Style.ink
        font.pixelSize: Style.titleSize
        font.weight: Font.DemiBold
        font.features: { "tnum": 1 }
    }

    Toggle {
        visible: editor.isPdf && editor.pageCount > 1
        text: "Apply to all pages"
        checked: editor.cropAllPages
        onToggled: (on) => editor.setCropAllPages(on)
    }

    Rectangle {  // PDF note: cropping hides, it doesn't delete
        visible: editor.isPdf
        width: parent.width
        height: note.implicitHeight + 20
        radius: Style.radiusSmall
        color: Style.field
        border.width: 1
        border.color: Style.divider
        Row {
            x: 10
            y: 10
            spacing: 8
            Icon { name: "info"; size: 16; color: Style.inkSoft }
            Text {
                textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                id: note
                width: panel.width - 40 - 44
                text: "The cut-off part is hidden, not removed: it is still in the file. Use Redact to remove content for good."
                color: Style.inkSoft
                font.pixelSize: Style.smallSize
                wrapMode: Text.WordWrap
            }
        }
    }

    Item { width: 1; height: 4 }
    Row {
        spacing: 8
        PillButton {
            text: "Reset"
            enabled: editor.hasCrop
            onClicked: editor.clearCrop()
        }
        PillButton {
            text: "Done"
            icon: "check"
            onClicked: editor.setTool("edit")
        }
    }
}
