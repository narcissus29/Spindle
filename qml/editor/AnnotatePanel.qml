import QtQuick
import "."

PanelPage {
    id: panel

    tool: "annotate"
    title: "Annotate"
    subtitle: editor.annotateTool === "select" ? "Click a mark to select it, drag to move it. Double-click text to edit it."
              : editor.annotateTool === "text" ? "Click where the text goes, type, then press Enter (Shift+Enter for a new line)."
              : "Draw on the page. Pick a color and a thickness below."

    readonly property var tools: [
        { name: "select", label: "Select", icon: "cursor", key: "V" },
        { name: "pen", label: "Pen", icon: "pen", key: "P" },
        { name: "highlight", label: "Highlight", icon: "highlighter", key: "H" },
        { name: "text", label: "Text", icon: "type", key: "T" },
        { name: "arrow", label: "Arrow", icon: "arrow", key: "A" },
        { name: "rect", label: "Box", icon: "square", key: "R" },
    ]

    Grid {
        columns: 3
        spacing: 7
        Repeater {
            model: panel.tools
            ToolChoice {
                required property var modelData
                icon: modelData.icon
                label: modelData.label
                key: modelData.key
                checked: editor.annotateTool === modelData.name
                onClicked: editor.setAnnotateTool(modelData.name)
            }
        }
    }

    Item { width: 1; height: 2 }
    SectionLabel { text: "Color" }
    Item {
        width: parent.width
        height: 30
        Row {
            id: swatchRow
            spacing: 7
            Repeater {
                model: editor.swatches
                Rectangle {
                    required property string modelData
                    readonly property bool current: editor.markColor.toLowerCase() === modelData
                    width: 24
                    height: 24
                    radius: 12
                    color: modelData
                    border.width: 1
                    border.color: Qt.rgba(0, 0, 0, 0.15)
                    scale: current ? 1.12 : (swArea.containsMouse ? 1.08 : 1)
                    Behavior on scale { NumberAnimation { duration: Style.d(Style.hoverMs); easing.type: Easing.OutBack } }
                    Rectangle {  // ring around the chosen one
                        anchors.centerIn: parent
                        width: parent.width + 6
                        height: width
                        radius: width / 2
                        color: "transparent"
                        border.width: 2
                        border.color: Style.accent
                        opacity: parent.current ? 1 : 0
                        Behavior on opacity { NumberAnimation { duration: Style.d(Style.fadeMs) } }
                    }
                    MouseArea {
                        id: swArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: editor.setMarkColor(parent.modelData)
                    }
                }
            }
        }
        IconButton {
            id: customButton
            anchors.left: swatchRow.right
            anchors.leftMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            size: 28
            iconSize: 16
            icon: "plus"
            tip: "Other color"
            checked: editor.swatches.indexOf(editor.markColor.toLowerCase()) < 0
            onClicked: picker.shown ? picker.shown = false : picker.open(editor.markColor)
        }
        ColorPicker {
            id: picker
            anchors.top: parent.bottom
            anchors.topMargin: 8
            anchors.right: parent.right
            onPicked: (c) => editor.setMarkColor(c.toString())
        }
    }

    Item { width: 1; height: 2 }
    SectionLabel { text: editor.annotateTool === "text" ? "Text size" : "Thickness" }
    Row {
        spacing: 8
        Repeater {
            model: 4
            Rectangle {
                required property int index
                readonly property bool current: editor.widthIndex === index
                width: 46
                height: 34
                radius: Style.radiusSmall
                color: current ? Style.accentSoft : (wArea.containsMouse ? Style.hover : Style.field)
                border.width: 1
                border.color: current ? Style.accentLine : Style.divider
                Behavior on color { ColorAnimation { duration: Style.d(Style.hoverMs) } }
                Rectangle {
                    visible: editor.annotateTool !== "text"
                    anchors.centerIn: parent
                    width: 24
                    height: [2, 4, 7, 11][parent.index]
                    radius: height / 2
                    color: parent.current ? Style.accent : Style.ink
                }
                Text {
                    textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                    visible: editor.annotateTool === "text"
                    anchors.centerIn: parent
                    text: ["S", "M", "L", "XL"][parent.index]
                    color: parent.current ? Style.accent : Style.ink
                    font.pixelSize: [11, 13, 15, 17][parent.index]
                    font.weight: Font.DemiBold
                }
                MouseArea {
                    id: wArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: editor.setWidthIndex(parent.index)
                }
            }
        }
    }

    Item { width: 1; height: 2 }
    Row {
        spacing: 8
        visible: opacity > 0
        opacity: editor.selectedMark >= 0 ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Style.d(Style.fadeMs) } }
        PillButton {
            danger: true
            icon: "trash"
            text: "Delete"
            onClicked: editor.deleteMark(editor.selectedMark)
        }
        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            anchors.verticalCenter: parent.verticalCenter
            text: "or press Delete"
            color: Style.inkSoft
            font.pixelSize: Style.smallSize
        }
    }

    Rectangle {
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
                text: "Saved as real PDF annotations, so other apps can still edit or remove them. To make them part of the page, tick “Flatten annotations” when saving."
                color: Style.inkSoft
                font.pixelSize: Style.smallSize
                wrapMode: Text.WordWrap
            }
        }
    }
}
