import QtQuick
import "."

// The tools, top to bottom. The highlight glides to the selected one.
Item {
    id: rail

    readonly property var tools: [
        { name: "crop", label: "Crop", icon: "crop", key: "Ctrl+1" },
        { name: "edit", label: editor.isPdf ? "Pages" : "Adjust", icon: "edit", key: "Ctrl+2" },
        { name: "annotate", label: "Annotate", icon: "annotate", key: "Ctrl+3" },
        { name: "redact", label: "Redact", icon: "redact", key: "Ctrl+4" },
        { name: "metadata", label: "Info", icon: "metadata", key: "Ctrl+5" },
    ]
    readonly property int selected: {
        for (let i = 0; i < tools.length; i++)
            if (tools[i].name === editor.tool) return i
        return 0
    }
    readonly property real itemH: 64

    width: 80

    Rectangle {  // selection
        x: 8
        width: parent.width - 16
        height: rail.itemH - 6
        y: column.y + rail.selected * rail.itemH + 3
        radius: Style.radius
        color: Style.accentSoft
        border.width: 1
        border.color: Style.accentLine
        Behavior on y { NumberAnimation { duration: Style.d(Style.panelMs); easing.type: Easing.OutCubic } }
    }

    Column {
        id: column
        y: 6
        width: parent.width

        Repeater {
            model: rail.tools
            Item {
                id: item
                required property var modelData
                required property int index
                readonly property bool current: index === rail.selected
                width: column.width
                height: rail.itemH

                Rectangle {  // hover
                    x: 8
                    y: 3
                    width: parent.width - 16
                    height: parent.height - 6
                    radius: Style.radius
                    color: ma.containsMouse && !item.current ? Style.hover : Style.clear
                    Behavior on color { ColorAnimation { duration: Style.d(Style.hoverMs) } }
                }
                Column {
                    anchors.centerIn: parent
                    spacing: 4
                    Icon {
                        anchors.horizontalCenter: parent.horizontalCenter
                        name: item.modelData.icon
                        size: 22
                        color: item.current ? Style.accent : Style.ink
                        Behavior on color { ColorAnimation { duration: Style.d(Style.fadeMs) } }
                    }
                    Text {
                        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: item.modelData.label
                        color: item.current ? Style.accent : Style.inkSoft
                        font.pixelSize: 12
                        font.weight: item.current ? Font.DemiBold : Font.Normal
                    }
                }
                MouseArea {
                    id: ma
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: editor.setTool(item.modelData.name)
                    onContainsMouseChanged: if (!containsMouse) tipDelay.shown = false
                }
                Timer {
                    id: tipDelay
                    property bool shown: false
                    interval: 600
                    running: ma.containsMouse && !shown
                    onTriggered: shown = true
                }
                Tip { text: item.modelData.label + "  (" + item.modelData.key + ")"; show: tipDelay.shown && ma.containsMouse; side: "right" }
            }
        }
    }
}
