import QtQuick
import "."

// Images: turn / flip, and brightness / contrast / saturation.
PanelPage {
    id: panel

    required property QtObject live

    tool: "edit"
    title: "Adjust"
    subtitle: "Changes show right away and are applied when you save a copy."

    SectionLabel { text: "Rotate and flip" }
    Row {
        spacing: 6
        IconButton { icon: "rotate-ccw"; tip: "Rotate left  (Ctrl+Shift+R)"; onClicked: editor.rotate(-1) }
        IconButton { icon: "rotate-cw"; tip: "Rotate right  (Ctrl+R)"; onClicked: editor.rotate(1) }
        Item { width: 10; height: 1 }
        IconButton { icon: "flip-h"; tip: "Flip horizontally"; onClicked: editor.flip("h") }
        IconButton { icon: "flip-v"; tip: "Flip vertically"; onClicked: editor.flip("v") }
    }

    Item { width: 1; height: 2 }
    SectionLabel { text: "Light and color" }

    Repeater {
        model: [
            { key: "brightness", label: "Brightness" },
            { key: "contrast", label: "Contrast" },
            { key: "saturation", label: "Saturation" },
        ]
        SliderRow {
            required property var modelData
            objectName: "slider-" + modelData.key
            label: modelData.label
            value: editor[modelData.key]
            onMoved: (v) => { panel.live[modelData.key] = v }
            onCommitted: (v) => {
                editor.setAdjust(modelData.key, v)
                const key = modelData.key
                panel.live[key] = Qt.binding(() => editor[key])
            }
        }
    }

    PillButton {
        text: "Reset colors"
        enabled: editor.brightness !== 0 || editor.contrast !== 0 || editor.saturation !== 0
        onClicked: editor.resetAdjust()
    }
}
