import QtQuick
import "."

// A tool button with an icon over a label (Annotate's tools).
Item {
    id: tc

    property string icon
    property string label
    property string key
    property bool checked: false
    signal clicked()

    width: 76
    height: 58

    Rectangle {
        anchors.fill: parent
        radius: Style.radius
        color: tc.checked ? Style.accentSoft : (area.containsMouse ? Style.hover : Style.field)
        border.width: 1
        border.color: tc.checked ? Style.accentLine : Style.divider
        Behavior on color { ColorAnimation { duration: Style.d(Style.hoverMs) } }
    }
    Column {
        anchors.centerIn: parent
        spacing: 3
        Icon {
            anchors.horizontalCenter: parent.horizontalCenter
            name: tc.icon
            size: 20
            color: tc.checked ? Style.accent : Style.ink
        }
        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            anchors.horizontalCenter: parent.horizontalCenter
            text: tc.label
            color: tc.checked ? Style.accent : Style.inkSoft
            font.pixelSize: 11
            font.weight: tc.checked ? Font.DemiBold : Font.Normal
        }
    }
    scale: area.pressed ? 0.95 : 1
    Behavior on scale { NumberAnimation { duration: Style.d(110); easing.type: Easing.OutCubic } }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: tc.clicked()
        onContainsMouseChanged: if (!containsMouse) tipDelay.shown = false
    }
    Timer {
        id: tipDelay
        property bool shown: false
        interval: 600
        running: area.containsMouse && !shown
        onTriggered: shown = true
    }
    Tip { text: tc.label + "  (" + tc.key + ")"; show: tipDelay.shown && area.containsMouse; side: "below" }
}
