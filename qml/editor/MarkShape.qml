import QtQuick
import QtQuick.Shapes
import "."
import "Geometry.js" as Geo

// One mark, in content units (the parent layer is scaled by the zoom).
// Only the shape its type needs is created.
Item {
    id: ms

    property var mark: null
    property bool mirrored: false
    property real pixelScale: 1  // screen pixels per content unit (sharp highlighter layers)
    property real dx: 0
    property real dy: 0

    readonly property string kind: mark ? mark.type : ""
    readonly property color base: mark ? mark.color : "black"

    x: dx
    y: dy
    visible: mark !== null

    Loader {
        active: ms.mark !== null
        sourceComponent: ms.kind === "pen" ? pen : ms.kind === "highlight" ? highlight : ms.kind === "arrow" ? arrow
                         : ms.kind === "rect" ? rectangle : ms.kind === "text" ? text : null
    }

    Component {
        id: pen
        Shape {
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: ms.base
                strokeWidth: ms.mark.width
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                joinStyle: ShapePath.RoundJoin
                PathPolyline { path: Geo.toPoints(ms.mark.points.length > 1 ? ms.mark.points
                                                  : [ms.mark.points[0], [ms.mark.points[0][0] + 0.01, ms.mark.points[0][1]]]) }
            }
        }
    }

    Component {
        id: highlight
        // Drawn opaque into its own layer, which is then shown see-through
        // once: the whole stroke has one even tint, also where it crosses
        // itself (a see-through stroke would darken its own overlaps).
        // The layer covers just the stroke, at screen resolution.
        Item {
            id: hl
            // The box grows in steps of 256 screen pixels, so a stroke being
            // drawn rarely needs a new (resized) layer texture.
            readonly property real step: 256 / Math.max(ms.pixelScale, 1e-3)
            readonly property var raw: Geo.bounds(ms.mark)
            readonly property var b: [Math.floor(raw[0] / step) * step, Math.floor(raw[1] / step) * step,
                                      Math.ceil(raw[2] / step) * step, Math.ceil(raw[3] / step) * step]
            x: b[0]
            y: b[1]
            width: Math.max(1, b[2] - b[0])
            height: Math.max(1, b[3] - b[1])
            opacity: 0.38
            layer.enabled: true
            layer.smooth: true
            layer.textureSize: Qt.size(Math.min(4096, Math.ceil(width * ms.pixelScale)),
                                       Math.min(4096, Math.ceil(height * ms.pixelScale)))
            Shape {
                x: -hl.b[0]
                y: -hl.b[1]
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: ms.base
                    strokeWidth: ms.mark.width
                    fillColor: "transparent"
                    capStyle: ShapePath.RoundCap
                    joinStyle: ShapePath.RoundJoin
                    PathPolyline { path: Geo.toPoints(ms.mark.points.length > 1 ? ms.mark.points
                                                      : [ms.mark.points[0], [ms.mark.points[0][0] + 0.01, ms.mark.points[0][1]]]) }
                }
            }
        }
    }

    Component {
        id: arrow
        Shape {
            id: arrowShape
            readonly property var head: Geo.arrowHead(ms.mark.p1, ms.mark.p2, ms.mark.width)
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: ms.base
                strokeWidth: ms.mark.width
                fillColor: "transparent"
                capStyle: ShapePath.FlatCap
                PathPolyline { path: Geo.toPoints([ms.mark.p1, arrowShape.head.base]) }
            }
            ShapePath {
                strokeWidth: -1
                strokeColor: "transparent"
                fillColor: ms.base
                PathPolyline { path: Geo.toPoints([arrowShape.head.tip, arrowShape.head.left, arrowShape.head.right, arrowShape.head.tip]) }
            }
        }
    }

    Component {
        id: rectangle
        Rectangle {
            x: ms.mark.rect[0]
            y: ms.mark.rect[1]
            width: ms.mark.rect[2]
            height: ms.mark.rect[3]
            color: "transparent"
            border.width: ms.mark.width
            border.color: ms.base
        }
    }

    Component {
        id: text
        Text {
            x: ms.mark.rect[0]
            y: ms.mark.rect[1]
            width: ms.mark.rect[2]
            height: ms.mark.rect[3]
            text: ms.mark.text
            color: ms.base
            font.family: "Helvetica"
            font.pixelSize: ms.mark.size
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            // readable on a mirrored image, as in the saved file
            transform: Scale { origin.x: ms.mark.rect[2] / 2; xScale: ms.mirrored ? -1 : 1 }
        }
    }
}
