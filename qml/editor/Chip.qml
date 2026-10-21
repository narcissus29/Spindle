import QtQuick
import "."

// One choice in a row of choices (aspect ratio presets).
Item {
    id: chip

    property string text
    property bool checked: false

    signal clicked()

    implicitWidth: label.implicitWidth + 22
    implicitHeight: 30
    width: implicitWidth
    height: implicitHeight

    Rectangle {
        anchors.fill: parent
        radius: Style.radiusSmall
        color: chip.checked ? Style.accentSoft : (ma.containsMouse ? Style.hover : Style.field)
        border.width: 1
        border.color: chip.checked ? Style.accentLine : Style.panelBorder
        Behavior on color { ColorAnimation { duration: Style.d(Style.hoverMs) } }
        Behavior on border.color { ColorAnimation { duration: Style.d(Style.hoverMs) } }
    }

    Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        id: label
        anchors.centerIn: parent
        text: chip.text
        color: chip.checked ? Style.accent : Style.ink
        font.pixelSize: Style.smallSize + 1
        font.weight: chip.checked ? Font.DemiBold : Font.Normal
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: chip.clicked()
    }
}
