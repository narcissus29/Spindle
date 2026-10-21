import QtQuick
import "."

// Square icon button with hover tint, press scale and a delayed tooltip.
Item {
    id: btn

    property string icon
    property string tip
    property string tipSide: "below"
    property bool checked: false
    property bool danger: false
    property real size: 36
    property real iconSize: 20

    signal clicked()

    width: size
    height: size
    opacity: enabled ? 1 : 0.38
    Behavior on opacity { NumberAnimation { duration: Style.d(Style.fadeMs) } }

    Rectangle {
        anchors.fill: parent
        radius: Style.radiusSmall
        color: btn.checked ? Style.accentSoft : (ma.containsMouse ? Style.hover : Style.clear)
        Behavior on color { ColorAnimation { duration: Style.d(Style.hoverMs); easing.type: Easing.OutCubic } }
    }

    Icon {
        anchors.centerIn: parent
        name: btn.icon
        size: btn.iconSize
        color: btn.checked ? Style.accent : btn.danger ? Style.danger : Style.ink
        scale: ma.pressed ? 0.88 : 1
        Behavior on scale { NumberAnimation { duration: Style.d(110); easing.type: Easing.OutCubic } }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: btn.clicked()
        onContainsMouseChanged: if (!containsMouse) tipDelay.shown = false
    }

    // Runs only while the pointer rests on the button.
    Timer {
        id: tipDelay
        property bool shown: false
        interval: 450
        running: ma.containsMouse && !shown && btn.tip !== ""
        onTriggered: shown = true
    }

    Tip { text: btn.tip; show: tipDelay.shown && ma.containsMouse; side: btn.tipSide }
}
