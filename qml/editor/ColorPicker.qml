import QtQuick
import "."

// A small pop-over color picker: saturation / brightness square and a hue
// strip. Opens under its anchor; `picked(color)` on every change.
Rectangle {
    id: picker

    property color value: "#e5322d"
    property bool shown: false
    signal picked(color c)

    property real hue: 0
    property real sat: 1
    property real val: 1

    function open(c) {
        const col = Qt.color(c)
        hue = Math.max(0, col.hsvHue)
        sat = col.hsvSaturation
        val = col.hsvValue
        shown = true
    }
    function emitColor() {
        value = Qt.hsva(hue, sat, val, 1)
        picked(value)
    }

    width: 236
    height: 214
    radius: Style.radius
    color: Style.panel
    border.width: 1
    border.color: Style.panelBorder
    z: 60
    visible: opacity > 0.001
    opacity: shown ? 1 : 0
    scale: shown ? 1 : 0.95
    transformOrigin: Item.Top
    Behavior on opacity { NumberAnimation { duration: Style.d(Style.fadeMs); easing.type: Easing.OutCubic } }
    Behavior on scale { NumberAnimation { duration: Style.d(Style.panelMs); easing.type: Easing.OutCubic } }

    Rectangle {  // shadow
        z: -1
        anchors.fill: parent
        anchors.topMargin: 4
        anchors.bottomMargin: -6
        radius: parent.radius
        color: Style.cardShadow
    }

    Item {
        id: square
        x: 12
        y: 12
        width: parent.width - 24
        height: 132
        Rectangle {
            anchors.fill: parent
            radius: 6
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "white" }
                GradientStop { position: 1; color: Qt.hsva(picker.hue, 1, 1, 1) }
            }
        }
        Rectangle {
            anchors.fill: parent
            radius: 6
            gradient: Gradient {
                GradientStop { position: 0; color: "transparent" }
                GradientStop { position: 1; color: "black" }
            }
        }
        Rectangle {  // marker
            width: 14
            height: 14
            radius: 7
            x: picker.sat * square.width - 7
            y: (1 - picker.val) * square.height - 7
            color: "transparent"
            border.width: 2
            border.color: picker.val > 0.5 ? "black" : "white"
        }
        MouseArea {
            anchors.fill: parent
            preventStealing: true
            function pick(m) {
                picker.sat = Math.max(0, Math.min(1, m.x / width))
                picker.val = Math.max(0, Math.min(1, 1 - m.y / height))
                picker.emitColor()
            }
            onPressed: (m) => pick(m)
            onPositionChanged: (m) => { if (pressed) pick(m) }
        }
    }

    Item {
        id: hueStrip
        x: 12
        anchors.top: square.bottom
        anchors.topMargin: 12
        width: square.width
        height: 16
        Rectangle {
            anchors.fill: parent
            radius: 8
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.000; color: "#ff0000" }
                GradientStop { position: 0.167; color: "#ffff00" }
                GradientStop { position: 0.333; color: "#00ff00" }
                GradientStop { position: 0.500; color: "#00ffff" }
                GradientStop { position: 0.667; color: "#0000ff" }
                GradientStop { position: 0.833; color: "#ff00ff" }
                GradientStop { position: 1.000; color: "#ff0000" }
            }
        }
        Rectangle {
            width: 8
            height: 20
            radius: 4
            y: -2
            x: picker.hue * hueStrip.width - 4
            color: "white"
            border.width: 1
            border.color: Qt.rgba(0, 0, 0, 0.35)
        }
        MouseArea {
            anchors.fill: parent
            anchors.margins: -4
            preventStealing: true
            function pick(m) {
                picker.hue = Math.max(0, Math.min(0.999, (m.x - 4) / hueStrip.width))
                picker.emitColor()
            }
            onPressed: (m) => pick(m)
            onPositionChanged: (m) => { if (pressed) pick(m) }
        }
    }

    Row {
        x: 12
        anchors.top: hueStrip.bottom
        anchors.topMargin: 12
        spacing: 8
        Rectangle {
            width: 22
            height: 22
            radius: 11
            color: picker.value
            border.width: 1
            border.color: Style.panelBorder
        }
        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            anchors.verticalCenter: parent.verticalCenter
            text: picker.value.toString().toUpperCase()
            color: Style.inkSoft
            font.pixelSize: Style.smallSize
            font.features: { "tnum": 1 }
        }
    }
    PillButton {
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 8
        implicitHeight: 28
        text: "Done"
        onClicked: picker.shown = false
    }
}
