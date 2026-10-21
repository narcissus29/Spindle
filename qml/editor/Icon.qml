import QtQuick
import QtQuick.Shapes
import "."

// A 24x24 stroke icon from assets/icons, drawn as a vector path.
Item {
    id: root

    property string name
    property color color: Style.ink
    property real size: 20
    property real stroke: 1.9

    width: size
    height: size
    // The software renderer paints shapes without the clip of a scrolled
    // list: as a cached layer they are clipped like any image.
    layer.enabled: editor.software
    layer.smooth: true

    Shape {
        width: 24
        height: 24
        scale: root.size / 24
        transformOrigin: Item.TopLeft
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            fillColor: "transparent"
            strokeColor: root.color
            strokeWidth: root.stroke
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: editor.icon(root.name) }
        }
    }
}
