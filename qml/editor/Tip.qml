import QtQuick
import "."

// Tooltip bubble next to its parent. `side`: "below", "above", "right".
Rectangle {
    id: tip

    property string text
    property bool show: false
    property string side: "below"
    readonly property Item target: parent

    visible: opacity > 0
    opacity: show && text !== "" ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: Style.d(120); easing.type: Easing.OutCubic } }

    z: 1000
    radius: 7
    color: Style.tipBg
    width: label.implicitWidth + 16
    height: label.implicitHeight + 10
    x: side === "right" ? target.width + 8 : (target.width - width) / 2
    y: side === "below" ? target.height + 6 : side === "above" ? -height - 6 : (target.height - height) / 2

    Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        id: label
        anchors.centerIn: parent
        text: tip.text
        color: "white"
        font.pixelSize: Style.smallSize
    }
}
