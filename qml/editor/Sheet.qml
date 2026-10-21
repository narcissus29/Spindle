import QtQuick
import "."

// A modal card over a dimmed window: fades in and grows slightly.
// Esc (or cancel()) closes it.
Item {
    id: sheet

    property bool shown: false
    property real cardWidth: 420
    default property alias content: body.data

    signal canceled()

    function open() { shown = true; card.forceActiveFocus() }
    function close() { shown = false }

    anchors.fill: parent
    visible: opacity > 0.001
    opacity: shown ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: Style.d(Style.panelMs); easing.type: Easing.OutCubic } }
    z: 50

    Rectangle {
        anchors.fill: parent
        color: Style.scrim
    }
    MouseArea {  // eats clicks and wheel behind the card
        anchors.fill: parent
        onWheel: (w) => { w.accepted = true }
    }

    Rectangle {
        id: card
        anchors.centerIn: parent
        width: sheet.cardWidth
        height: body.implicitHeight + 48
        radius: Style.radius + 4
        color: Style.panel
        border.width: 1
        border.color: Style.panelBorder
        scale: sheet.shown ? 1 : 0.96
        Behavior on scale { NumberAnimation { duration: Style.d(Style.panelMs); easing.type: Easing.OutCubic } }
        focus: sheet.shown
        Keys.onEscapePressed: { sheet.canceled(); sheet.close() }

        Column {
            id: body
            x: 24
            y: 24
            width: parent.width - 48
            spacing: 14
        }
    }
}
