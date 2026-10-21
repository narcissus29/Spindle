import QtQuick
import "."

// File name on the left; undo / redo and "Save copy" on the right.
Item {
    id: bar

    signal saveClicked()

    height: 60

    Row {
        anchors.left: parent.left
        anchors.leftMargin: 18
        anchors.verticalCenter: parent.verticalCenter
        spacing: 10

        Rectangle {  // format badge, like the wheel's hub
            anchors.verticalCenter: parent.verticalCenter
            width: badge.implicitWidth + 14
            height: 22
            radius: 6
            color: Style.accentSoft
            Text {
                textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                id: badge
                anchors.centerIn: parent
                text: editor.formatLabel
                color: Style.accent
                font.pixelSize: 11
                font.weight: Font.Bold
                font.letterSpacing: 0.4
            }
        }
        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            anchors.verticalCenter: parent.verticalCenter
            text: editor.fileName
            color: Style.ink
            font.pixelSize: Style.titleSize
            font.weight: Font.DemiBold
            elide: Text.ElideMiddle
            width: Math.min(implicitWidth, bar.width - 420)
        }
        Rectangle {  // "edited" marker
            anchors.verticalCenter: parent.verticalCenter
            width: edited.implicitWidth + 14
            height: 20
            radius: 10
            color: Style.field
            border.width: 1
            border.color: Style.panelBorder
            opacity: editor.modified ? 1 : 0
            scale: editor.modified ? 1 : 0.85
            Behavior on opacity { NumberAnimation { duration: Style.d(Style.fadeMs) } }
            Behavior on scale { NumberAnimation { duration: Style.d(Style.panelMs); easing.type: Easing.OutBack } }
            Text {
                textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                id: edited
                anchors.centerIn: parent
                text: "Edited"
                color: Style.inkSoft
                font.pixelSize: 11
            }
        }
    }

    Row {
        anchors.right: parent.right
        anchors.rightMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        spacing: 6

        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            icon: "undo"
            enabled: editor.canUndo
            tip: editor.canUndo ? "Undo " + editor.undoText.toLowerCase() + "  (Ctrl+Z)" : "Undo  (Ctrl+Z)"
            onClicked: editor.undo()
        }
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            icon: "redo"
            enabled: editor.canRedo
            tip: editor.canRedo ? "Redo " + editor.redoText.toLowerCase() + "  (Ctrl+Shift+Z)" : "Redo  (Ctrl+Shift+Z)"
            onClicked: editor.redo()
        }
        Item { width: 8; height: 1 }
        PillButton {
            anchors.verticalCenter: parent.verticalCenter
            primary: true
            icon: "save"
            text: "Save copy"
            busy: editor.saving
            onClicked: bar.saveClicked()
        }
    }
}
