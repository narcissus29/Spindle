import QtQuick
import "."

// One tool's panel. Shown when its tool is selected: it fades and slides
// in, the previous one fades out (both live, so the switch crossfades).
Item {
    id: page

    property string tool
    property string title
    property string subtitle
    default property alias content: body.data
    readonly property real bodyTop: body.y  // for content that fills the rest of the panel

    readonly property bool current: editor.tool === tool
    anchors.fill: parent
    visible: opacity > 0.001
    opacity: current ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: Style.d(Style.panelMs); easing.type: Easing.OutCubic } }
    transform: Translate {
        y: page.current ? 0 : 10
        Behavior on y { NumberAnimation { duration: Style.d(Style.panelMs); easing.type: Easing.OutCubic } }
    }
    enabled: current

    Column {
        id: head
        x: 20
        y: 20
        width: parent.width - 40
        spacing: 4
        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            text: page.title
            color: Style.ink
            font.pixelSize: Style.titleSize + 2
            font.weight: Font.DemiBold
        }
        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            width: parent.width
            visible: text !== ""
            text: page.subtitle
            color: Style.inkSoft
            font.pixelSize: Style.smallSize
            wrapMode: Text.WordWrap
        }
    }

    Column {
        id: body
        x: 20
        anchors.top: head.bottom
        anchors.topMargin: 18
        width: parent.width - 40
        spacing: 14
    }
}
