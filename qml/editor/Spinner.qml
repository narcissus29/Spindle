import QtQuick
import QtQuick.Shapes
import "."

// Small busy arc. Animates only while visible.
Item {
    id: sp

    property color color: "white"
    property real size: 16

    width: size
    height: size

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        RotationAnimator on rotation {
            from: 0; to: 360; duration: 900; loops: Animation.Infinite
            running: sp.visible
        }
        ShapePath {
            fillColor: "transparent"
            strokeColor: sp.color
            strokeWidth: 2
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: sp.size / 2; centerY: sp.size / 2
                radiusX: sp.size / 2 - 1.5; radiusY: sp.size / 2 - 1.5
                startAngle: 0; sweepAngle: 270
            }
        }
    }
}
