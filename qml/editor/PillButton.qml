import QtQuick
import "."

// Rounded text button. `primary`: the accent gradient (Save); `danger`: red text.
Item {
    id: b

    property string text
    property string icon
    property bool primary: false
    property bool danger: false
    property bool busy: false

    signal clicked()

    implicitWidth: row.implicitWidth + 30
    implicitHeight: 36
    width: implicitWidth
    height: implicitHeight
    opacity: enabled ? 1 : 0.45
    Behavior on opacity { NumberAnimation { duration: Style.d(Style.fadeMs) } }
    scale: ma.pressed ? 0.97 : 1
    Behavior on scale { NumberAnimation { duration: Style.d(110); easing.type: Easing.OutCubic } }

    Gradient {
        id: accentFill
        GradientStop { position: 0; color: Style.accentTop }
        GradientStop { position: 1; color: Style.accent }
    }

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        gradient: b.primary ? accentFill : null
        color: b.danger ? Style.dangerSoft : Style.panel
        border.width: b.primary ? 0 : 1
        border.color: b.danger ? Qt.rgba(0.70, 0.15, 0.12, 0.25) : Style.panelBorder
    }

    Rectangle {  // hover tint
        anchors.fill: parent
        radius: height / 2
        color: b.primary ? Qt.rgba(1, 1, 1, ma.containsMouse ? 0.14 : 0) : (ma.containsMouse ? Style.hover : Style.clear)
        Behavior on color { ColorAnimation { duration: Style.d(Style.hoverMs) } }
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 7

        Spinner {
            visible: b.busy
            anchors.verticalCenter: parent.verticalCenter
            color: b.primary ? "white" : Style.accent
        }
        Icon {
            visible: !b.busy && b.icon !== ""
            anchors.verticalCenter: parent.verticalCenter
            name: b.icon
            size: 17
            color: b.primary ? "white" : b.danger ? Style.danger : Style.ink
        }
        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            anchors.verticalCenter: parent.verticalCenter
            text: b.text
            color: b.primary ? "white" : b.danger ? Style.danger : Style.ink
            font.pixelSize: Style.textSize
            font.weight: Font.DemiBold
        }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: if (!b.busy) b.clicked()
    }
}
