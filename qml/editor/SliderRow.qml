import QtQuick
import "."

// A -1..1 slider with the zero point in the middle (brightness etc.).
// While dragging it reports moved(v) for the live preview; on release it
// reports committed(v) once, which becomes one undo step. Double-click
// resets to 0. Arrow keys nudge by 1, committed after a short pause.
Item {
    id: row

    property string label
    property real value: 0  // committed value (bound by the owner)

    signal moved(real v)
    signal committed(real v)

    property bool dragging: false
    property real dragValue: 0
    readonly property real shown: dragging ? dragValue : value
    readonly property int percent: Math.round(shown * 100)

    width: parent ? parent.width : 240
    implicitHeight: 52
    height: implicitHeight
    activeFocusOnTab: true

    function valueAt(x) {
        const v = ((x - track.x) / track.width) * 2 - 1
        const c = Math.max(-1, Math.min(1, v))
        return Math.abs(c) < 0.025 ? 0 : c  // snap to the middle
    }

    function nudge(step) {
        dragValue = Math.max(-1, Math.min(1, Math.round(((dragging ? dragValue : value) + step) * 100) / 100))
        dragging = true
        moved(dragValue)
        keyPause.restart()
    }

    Keys.onLeftPressed: nudge(-0.01)
    Keys.onRightPressed: nudge(0.01)

    Timer {  // runs only right after a key press
        id: keyPause
        interval: 450
        onTriggered: { row.dragging = false; row.committed(row.dragValue) }
    }

    Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        anchors.left: parent.left
        anchors.top: parent.top
        text: row.label
        color: Style.ink
        font.pixelSize: Style.textSize
    }

    Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        anchors.right: parent.right
        anchors.top: parent.top
        text: (row.percent > 0 ? "+" : "") + row.percent
        color: row.percent === 0 ? Style.inkFaint : Style.accent
        font.pixelSize: Style.textSize
        font.weight: Font.DemiBold
        font.features: { "tnum": 1 }
    }

    Item {
        id: track
        x: 9
        width: parent.width - 18
        y: 24
        height: 24

        Rectangle {  // groove
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            height: 4
            radius: 2
            color: Style.track
        }
        Rectangle {  // fill from the middle to the knob
            anchors.verticalCenter: parent.verticalCenter
            x: Math.min(knob.cx, track.width / 2)
            width: Math.abs(knob.cx - track.width / 2)
            height: 4
            radius: 2
            color: Style.accent
        }
        Rectangle {  // zero tick
            anchors.centerIn: parent
            width: 2
            height: 10
            radius: 1
            color: Style.inkFaint
        }
        Rectangle {
            id: knob
            readonly property real cx: (row.shown + 1) / 2 * track.width
            x: cx - width / 2
            anchors.verticalCenter: parent.verticalCenter
            width: 18
            height: 18
            radius: 9
            color: "white"
            border.width: row.activeFocus ? 2 : 1
            border.color: row.activeFocus ? Style.accent : Style.accentLine
            scale: row.dragging || area.containsMouse ? 1.12 : 1
            Behavior on scale { NumberAnimation { duration: Style.d(140); easing.type: Easing.OutCubic } }
        }

        MouseArea {
            id: area
            anchors.fill: parent
            anchors.margins: -6
            hoverEnabled: true
            preventStealing: true
            cursorShape: Qt.PointingHandCursor
            onPressed: (mouse) => {
                row.forceActiveFocus()
                row.dragValue = row.valueAt(mouse.x - 6 + track.x)
                row.dragging = true
                row.moved(row.dragValue)
            }
            onPositionChanged: (mouse) => {
                if (!pressed) return
                row.dragValue = row.valueAt(mouse.x - 6 + track.x)
                row.moved(row.dragValue)
            }
            onReleased: { row.dragging = false; row.committed(row.dragValue) }
            onCanceled: { row.dragging = false; row.committed(row.dragValue) }
            onDoubleClicked: { row.dragging = false; row.committed(0) }
        }
    }
}
