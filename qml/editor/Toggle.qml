import QtQuick
import "."

// A labelled switch. It doesn't change `checked` itself: it asks via
// toggled(), and the owner's binding updates it.
Item {
    id: t

    property string text
    property bool checked: false

    signal toggled(bool on)

    implicitHeight: 30
    width: parent ? parent.width : 200
    height: implicitHeight

    Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        anchors.left: parent.left
        anchors.right: track.left
        anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        text: t.text
        color: Style.ink
        font.pixelSize: Style.textSize
        elide: Text.ElideRight
    }

    Rectangle {
        id: track
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: 36
        height: 20
        radius: 10
        color: t.checked ? Style.accent : Style.track
        Behavior on color { ColorAnimation { duration: Style.d(180) } }

        Rectangle {
            width: 16
            height: 16
            radius: 8
            y: 2
            x: t.checked ? parent.width - width - 2 : 2
            color: "white"
            border.width: 1
            border.color: Qt.rgba(0, 0, 0, 0.06)
            Behavior on x { NumberAnimation { duration: Style.d(180); easing.type: Easing.OutCubic } }
        }
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: t.toggled(!t.checked)
    }
}
