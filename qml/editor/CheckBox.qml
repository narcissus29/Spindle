import QtQuick
import "."

// A labelled tick box. Like Toggle, it asks (toggled) and the owner's
// binding sets `checked`.
Item {
    id: cb

    property string text
    property bool checked: false

    signal toggled(bool on)

    implicitWidth: box.width + 8 + label.implicitWidth
    implicitHeight: Math.max(22, label.implicitHeight)
    width: implicitWidth
    height: implicitHeight

    Rectangle {
        id: box
        anchors.verticalCenter: parent.verticalCenter
        width: 18
        height: 18
        radius: 5
        color: cb.checked ? Style.accent : Style.panel
        border.width: cb.checked ? 0 : 1.5
        border.color: area.containsMouse ? Style.accentLine : Style.inkFaint
        Behavior on color { ColorAnimation { duration: Style.d(Style.fadeMs) } }
        Icon {
            anchors.centerIn: parent
            name: "check"
            size: 14
            stroke: 2.6
            color: "white"
            opacity: cb.checked ? 1 : 0
            scale: cb.checked ? 1 : 0.6
            Behavior on opacity { NumberAnimation { duration: Style.d(Style.fadeMs) } }
            Behavior on scale { NumberAnimation { duration: Style.d(Style.hoverMs); easing.type: Easing.OutBack } }
        }
    }
    Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        id: label
        anchors.left: box.right
        anchors.leftMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        text: cb.text
        color: Style.ink
        font.pixelSize: Style.textSize
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: cb.toggled(!cb.checked)
    }
}
