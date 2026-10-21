import QtQuick
import "../editor"

// Where you are in the welcome: one dot per step, the current one long.
Row {
    id: dots
    property int count: 3
    property int current: 0
    spacing: 6
    Repeater {
        model: dots.count
        Rectangle {
            required property int index
            height: 6
            width: index === dots.current ? 22 : 6
            radius: 3
            color: index === dots.current ? Style.accent : Style.track
            Behavior on width { NumberAnimation { duration: Style.d(Style.panelMs); easing.type: Easing.OutCubic } }
            Behavior on color { ColorAnimation { duration: Style.d(Style.panelMs) } }
        }
    }
}
