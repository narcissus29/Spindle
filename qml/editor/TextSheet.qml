import QtQuick
import "."

// Shows a long piece of text read-only (the raw XMP), scrollable and
// selectable. Esc or Close closes it.
Sheet {
    id: sheet

    property string heading
    property string body

    cardWidth: Math.min(680, parent ? parent.width - 80 : 680)

    Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        text: sheet.heading
        color: Style.ink
        font.pixelSize: Style.titleSize + 3
        font.weight: Font.DemiBold
    }

    Rectangle {
        width: parent.width
        height: Math.min(textView.contentHeight + 20, (sheet.parent ? sheet.parent.height : 600) * 0.6)
        radius: Style.radiusSmall
        color: Style.field
        border.width: 1
        border.color: Style.divider
        clip: true
        Flickable {
            id: textView
            anchors.fill: parent
            anchors.margins: 10
            contentWidth: width
            contentHeight: content.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            TextEdit {
                id: content
                width: textView.width
                text: sheet.body
                textFormat: TextEdit.PlainText  // XMP is XML: never read as rich text (no remote <img>)
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.WrapAnywhere
                color: Style.ink
                font.family: "monospace"
                font.pixelSize: Style.smallSize
            }
        }
    }

    Item {
        width: parent.width
        height: 40
        PillButton {
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            text: "Close"
            onClicked: sheet.close()
        }
    }
}
