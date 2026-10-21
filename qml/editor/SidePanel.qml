import QtQuick
import "."

// The right-hand card with the selected tool's options.
Rectangle {
    id: side

    required property Item vp
    required property QtObject live
    signal viewRequested(string key)

    radius: Style.radius + 2
    color: Style.panel
    border.width: 1
    border.color: Style.panelBorder

    CropPanel { vp: side.vp }
    AdjustPanel { visible: !editor.isPdf && opacity > 0.001; live: side.live }
    PagesPanel { visible: editor.isPdf && opacity > 0.001 }
    AnnotatePanel {}
    RedactPanel {}
    MetadataPanel { onViewRequested: (key) => side.viewRequested(key) }
}
