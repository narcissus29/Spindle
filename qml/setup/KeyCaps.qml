import QtQuick
import "../editor"

// "Ctrl + Alt + Space" drawn as key caps.
Row {
    id: caps

    property string keys: ""   // "Ctrl+Alt+Space"
    property bool faint: false

    spacing: 6
    Repeater {
        model: caps.keys === "" ? [] : setup.pretty(caps.keys).split(" + ")
        Rectangle {
            required property string modelData
            height: 30
            width: Math.max(30, label.implicitWidth + 18)
            radius: 7
            color: caps.faint ? Style.field : Style.panel
            border.width: 1
            border.color: Style.panelBorder
            Rectangle {  // the key's bottom edge
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                height: 3
                radius: 7
                color: Style.canvasEdge
            }
            Text {
                textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                id: label
                anchors.centerIn: parent
                anchors.verticalCenterOffset: -1
                text: modelData
                color: caps.faint ? Style.inkSoft : Style.ink
                font.pixelSize: Style.textSize
                font.weight: Font.DemiBold
            }
        }
    }
}
