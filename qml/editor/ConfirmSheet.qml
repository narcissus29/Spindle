import QtQuick
import "."

// Closing with unsaved edits.
Sheet {
    id: sheet

    cardWidth: 440
    signal discard()
    signal saveFirst()

    Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        text: "Discard your edits?"
        color: Style.ink
        font.pixelSize: Style.titleSize + 3
        font.weight: Font.DemiBold
    }
    Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        width: parent.width
        text: "Your changes to " + editor.fileName + " haven't been saved. The original file stays as it is either way."
        color: Style.inkSoft
        font.pixelSize: Style.textSize
        wrapMode: Text.WordWrap
    }
    Item {
        width: parent.width
        height: 40
        Row {
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            spacing: 8
            PillButton { text: "Cancel"; onClicked: sheet.close() }
            PillButton { danger: true; text: "Discard"; onClicked: { sheet.close(); sheet.discard() } }
            PillButton { primary: true; icon: "save"; text: "Save copy"; onClicked: { sheet.close(); sheet.saveFirst() } }
        }
    }
}
