import QtQuick
import QtQuick.Shapes
import QtQuick.Window
import "."
import "Geometry.js" as Geo

// Everything drawn on top of the page on screen: marks, redaction boxes,
// search matches, the stroke being drawn and the text being typed. It is
// sized in content units and scaled by the zoom, and it sits inside the
// page's rotation (and an image's mirror), so it turns with the page.
Item {
    id: marksRoot

    required property real k
    property bool mirrored: false
    property var live: null          // the mark being drawn
    property int moveId: -1          // the selected mark while it is dragged
    property real moveDx: 0
    property real moveDy: 0
    property int selectedBox: -1
    readonly property real px: 1 / k  // one screen pixel in content units
    readonly property real pixelScale: k * Screen.devicePixelRatio

    // Nothing is drawn outside the page (as in the saved file).
    clip: true

    // ---- typing text ----
    property bool editing: false
    property int editId: -1
    property real editX: 0
    property real editY: 0
    property int editSize: 16
    property color editColor: "black"
    property var editArea: [0, 0, width, height]  // where the text must stay: x0, y0, x1, y1
    readonly property real editMaxWidth: Math.max(editSize, editArea[2] - editX)

    // Text starts inside the visible page and stays there: it wraps at
    // the right edge and moves up rather than run off the bottom.
    function startText(x, y, size, color, text, id, area) {
        editArea = area
        editSize = Math.max(1, Math.round(size))
        editX = Math.max(area[0], Math.min(x, area[2] - editSize * 2))
        editY = Math.max(area[1], Math.min(y, area[3] - editSize * 1.3))
        editColor = color
        editId = id
        typing.text = text
        editing = true
        typing.forceActiveFocus()
        typing.cursorPosition = typing.length
    }
    function keepInside() {
        if (editing && editY + typing.contentHeight > editArea[3])
            editY = Math.max(editArea[1], editArea[3] - typing.contentHeight)
    }
    function commitText() {
        if (!editing) return
        const w = Math.min(Math.ceil(typing.contentWidth) + 1, editMaxWidth)
        const rect = [editX, editY, Math.max(w, 1), Math.max(typing.contentHeight, 1)]
        const id = editId
        editing = false
        editId = -1
        if (id < 0)
            editor.addMark({ type: "text", text: typing.text, size: editSize, color: editColor.toString(), rect: rect })
        else
            editor.updateMark(id, { text: typing.text, rect: rect })
    }
    function cancelText() {
        editing = false
        editId = -1
    }

    transformOrigin: Item.TopLeft
    scale: k

    readonly property var pageResults: editor.tool === "redact"
        ? editor.searchResults.filter(r => r.page === editor.page) : []

    // ---- search matches (Redact) ----
    Repeater {
        model: marksRoot.pageResults
        Repeater {
            id: match
            required property var modelData
            model: modelData.rects
            Rectangle {
                required property var modelData
                x: modelData[0] - 1.5 * marksRoot.px
                y: modelData[1] - 1.5 * marksRoot.px
                width: modelData[2] + 3 * marksRoot.px
                height: modelData[3] + 3 * marksRoot.px
                radius: 2 * marksRoot.px
                color: match.modelData.checked ? Qt.rgba(1.0, 0.72, 0.1, 0.30) : "transparent"
                border.width: 1.5 * marksRoot.px
                border.color: Qt.rgba(0.92, 0.55, 0.0, 0.9)
            }
        }
    }

    // ---- marks ----
    Repeater {
        model: editor.marks
        MarkShape {
            required property var modelData
            mark: modelData
            mirrored: marksRoot.mirrored
            pixelScale: marksRoot.pixelScale
            visible: modelData.id !== marksRoot.editId
            dx: modelData.id === marksRoot.moveId ? marksRoot.moveDx : 0
            dy: modelData.id === marksRoot.moveId ? marksRoot.moveDy : 0
        }
    }

    // ---- redaction boxes ----
    Repeater {
        model: editor.redactions
        Rectangle {
            required property var modelData
            readonly property bool selected: modelData.id === marksRoot.selectedBox
            x: modelData.rect[0]
            y: modelData.rect[1]
            width: modelData.rect[2]
            height: modelData.rect[3]
            color: editor.redactPreview ? "black" : Qt.rgba(0.05, 0.06, 0.09, 0.58)
            Behavior on color { ColorAnimation { duration: Style.d(Style.fadeMs) } }
            border.width: editor.redactPreview && !selected ? 0 : 2 * marksRoot.px
            border.color: selected ? Style.accent : "#e5322d"
        }
    }

    // ---- the mark / box being drawn ----
    MarkShape {
        mark: marksRoot.live && marksRoot.live.type !== "redact" ? marksRoot.live : null
        mirrored: marksRoot.mirrored
        pixelScale: marksRoot.pixelScale
    }
    Rectangle {
        visible: marksRoot.live !== null && marksRoot.live.type === "redact"
        x: visible ? marksRoot.live.rect[0] : 0
        y: visible ? marksRoot.live.rect[1] : 0
        width: visible ? marksRoot.live.rect[2] : 0
        height: visible ? marksRoot.live.rect[3] : 0
        color: Qt.rgba(0.05, 0.06, 0.09, 0.58)
        border.width: 2 * marksRoot.px
        border.color: "#e5322d"
    }

    // ---- selection ----
    Shape {
        id: selection
        readonly property var mark: {
            const id = editor.selectedMark
            if (id < 0 || marksRoot.editing) return null
            for (const m of editor.marks) if (m.id === id) return m
            return null
        }
        readonly property var b: Geo.bounds(mark)
        readonly property real pad: 5 * marksRoot.px
        visible: mark !== null && editor.tool === "annotate"
        x: marksRoot.moveId === editor.selectedMark ? marksRoot.moveDx : 0
        y: marksRoot.moveId === editor.selectedMark ? marksRoot.moveDy : 0
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: Style.accent
            strokeWidth: 1.5 * marksRoot.px
            fillColor: Qt.rgba(Style.accent.r, Style.accent.g, Style.accent.b, 0.06)
            strokeStyle: ShapePath.DashLine
            dashPattern: [4, 3]
            PathPolyline {
                path: {
                    const b = selection.b, p = selection.pad
                    return Geo.toPoints([[b[0] - p, b[1] - p], [b[2] + p, b[1] - p], [b[2] + p, b[3] + p],
                                         [b[0] - p, b[3] + p], [b[0] - p, b[1] - p]])
                }
            }
        }
    }

    // ---- typing ----
    TextEdit {
        id: typing
        visible: marksRoot.editing
        x: marksRoot.editX
        y: marksRoot.editY
        font.family: "Helvetica"
        font.pixelSize: marksRoot.editSize
        color: marksRoot.editColor
        width: marksRoot.editMaxWidth
        wrapMode: TextEdit.WordWrap
        onContentHeightChanged: marksRoot.keepInside()
        selectByMouse: true
        textFormat: TextEdit.PlainText
        transform: Scale { origin.x: Math.max(typing.contentWidth, 1) / 2; xScale: marksRoot.mirrored ? -1 : 1 }
        Keys.onReturnPressed: (e) => {
            if (e.modifiers & Qt.ShiftModifier) e.accepted = false  // Shift+Enter: new line
            else marksRoot.commitText()
        }
        Keys.onEnterPressed: marksRoot.commitText()
        Keys.onEscapePressed: marksRoot.cancelText()

        Rectangle {
            z: -1
            x: -4 * marksRoot.px
            y: -3 * marksRoot.px
            width: Math.max(typing.contentWidth, marksRoot.editSize * 0.6) + 8 * marksRoot.px
            height: typing.contentHeight + 6 * marksRoot.px
            radius: 3 * marksRoot.px
            color: Qt.rgba(1, 1, 1, 0.55)
            border.width: 1.5 * marksRoot.px
            border.color: Style.accent
        }
    }
}
