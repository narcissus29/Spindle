import QtQuick
import "."

// A short message that rises from the bottom, with an optional action.
// Hides itself after a few seconds (the timer runs only while shown).
Item {
    id: toast

    property string text
    property string action
    property bool error: false
    property bool shown: false

    signal actionClicked()

    function show(message, actionText, isError) {
        text = message
        action = actionText || ""
        error = !!isError
        shown = true
        hideTimer.restart()
    }

    width: pill.width
    height: pill.height
    z: 40
    visible: opacity > 0.001
    opacity: shown ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: Style.d(Style.panelMs); easing.type: Easing.OutCubic } }
    transform: Translate {
        y: toast.shown ? 0 : 14
        Behavior on y { NumberAnimation { duration: Style.d(Style.panelMs); easing.type: Easing.OutCubic } }
    }

    Timer {
        id: hideTimer
        interval: toast.error ? 6000 : 4500
        onTriggered: toast.shown = false
    }

    Rectangle {
        id: pill
        width: row.implicitWidth + 32
        height: 44
        radius: 22
        color: Style.tipBg

        Row {
            id: row
            anchors.centerIn: parent
            spacing: 14
            Icon {
                anchors.verticalCenter: parent.verticalCenter
                name: toast.error ? "info" : "check"
                size: 18
                color: toast.error ? "#ffb4ab" : "#9fc2ff"
            }
            Text {
                textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                anchors.verticalCenter: parent.verticalCenter
                text: toast.text
                color: "white"
                font.pixelSize: Style.textSize
            }
            Text {
                textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                visible: toast.action !== ""
                anchors.verticalCenter: parent.verticalCenter
                text: toast.action
                color: actionArea.containsMouse ? "white" : "#9fc2ff"
                font.pixelSize: Style.textSize
                font.weight: Font.DemiBold
                MouseArea {
                    id: actionArea
                    anchors.fill: parent
                    anchors.margins: -8
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { toast.shown = false; toast.actionClicked() }
                }
            }
        }
    }
}
