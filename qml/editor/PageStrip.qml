import QtQuick
import "."

// PDF page thumbnails. Only the visible ones are created and rendered.
Item {
    id: strip

    readonly property var pages: editor.pages  // converted once per change, shared by delegates

    ListView {
        id: list
        anchors.fill: parent
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        orientation: ListView.Horizontal
        spacing: 12
        clip: true
        model: editor.pageCount
        currentIndex: editor.page
        highlightFollowsCurrentItem: true
        highlightMoveDuration: Style.d(260)
        highlightRangeMode: ListView.ApplyRange
        preferredHighlightBegin: width * 0.2
        preferredHighlightEnd: width * 0.8
        highlight: Item {}
        boundsBehavior: Flickable.StopAtBounds

        delegate: Item {
            id: cell
            required property int index
            readonly property var info: strip.pages[index] || { rot: 0, deleted: false, w: 1, h: 1 }
            readonly property bool current: index === editor.page
            readonly property bool sideways: info.rot % 180 !== 0
            readonly property real aspect: sideways ? info.h / info.w : info.w / info.h
            readonly property real thumbH: list.height - 28
            width: Math.max(40, Math.min(thumbH * aspect, thumbH * 1.6))
            height: list.height

            Rectangle {
                id: frame
                anchors.horizontalCenter: parent.horizontalCenter
                y: 4
                width: parent.width
                height: cell.thumbH
                radius: 5
                color: "white"
                border.width: cell.current ? 2 : 1
                border.color: cell.current ? Style.accent : Style.panelBorder
                Behavior on border.color { ColorAnimation { duration: Style.d(Style.fadeMs) } }
                clip: true

                Image {
                    anchors.centerIn: parent
                    width: cell.sideways ? parent.height - 4 : parent.width - 4
                    height: cell.sideways ? parent.width - 4 : parent.height - 4
                    rotation: cell.info.rot
                    Behavior on rotation { RotationAnimation { duration: Style.d(Style.turnMs); easing.type: Easing.OutCubic; direction: RotationAnimation.Shortest } }
                    source: "image://doc/thumb/" + cell.index
                    asynchronous: true
                    smooth: true
                    mipmap: true
                    opacity: (status === Image.Ready ? 1 : 0) * (cell.info.deleted ? 0.25 : 1)
                    Behavior on opacity { NumberAnimation { duration: Style.d(Style.fadeMs) } }
                }
                Icon {
                    anchors.centerIn: parent
                    visible: cell.info.deleted
                    name: "trash"
                    size: 20
                    color: Style.danger
                }
            }
            Text {
                textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: frame.bottom
                anchors.topMargin: 4
                text: cell.index + 1
                color: cell.current ? Style.accent : Style.inkSoft
                font.pixelSize: 11
                font.weight: cell.current ? Font.DemiBold : Font.Normal
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: editor.goToPage(cell.index)
            }
        }
    }
}
