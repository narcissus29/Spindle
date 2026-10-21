import QtQuick
import QtQuick.Shapes

// The hover fill. There is only one: it glides (rotates) from
// wedge to wedge along the shortest way round instead of jumping.
Item {
    id: hl

    required property Item wheel
    required property QtObject theme
    property real angle: 0
    property bool glide: false
    property bool fade: true

    readonly property bool shown: wheel.hoveredIndex >= 0

    rotation: angle
    opacity: shown ? 1 : 0
    visible: opacity > 0

    Behavior on opacity {
        enabled: hl.fade
        NumberAnimation { duration: hl.theme.d(hl.theme.fadeMs); easing.type: Easing.OutCubic }
    }
    Behavior on angle {
        enabled: hl.glide
        NumberAnimation { duration: hl.theme.d(hl.theme.hoverMs); easing.type: Easing.OutCubic }
    }

    // animate=false when appearing from "nothing hovered": snap into place,
    // then fade in, rather than sweeping in from the last position.
    function moveTo(i, animate) {
        if (i < 0)
            return
        const target = i * wheel.step
        if (!animate) {
            glide = false
            angle = target
            return
        }
        const delta = ((target - angle) % 360 + 540) % 360 - 180
        glide = true
        angle = angle + delta
    }

    Shape {
        anchors.fill: parent
        scale: hl.theme.hoverScale
        preferredRendererType: Shape.CurveRenderer

        // soft glow around the edge
        ShapePath {
            fillColor: "transparent"
            strokeColor: hl.theme.glow
            strokeWidth: hl.wheel.width * 0.016
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: hl.wheel.wedgePath }
        }

        ShapePath {
            strokeColor: hl.theme.hotEdge
            strokeWidth: 1
            joinStyle: ShapePath.RoundJoin
            fillGradient: RadialGradient {
                centerX: hl.wheel.c; centerY: hl.wheel.c
                centerRadius: hl.wheel.outerR
                focalX: hl.wheel.c; focalY: hl.wheel.c
                GradientStop { position: hl.wheel.innerR / hl.wheel.outerR; color: hl.theme.hotInner }
                GradientStop { position: 1.0; color: hl.theme.hotOuter }
            }
            PathSvg { path: hl.wheel.wedgePath }
        }

        // light along the outer edge so it still reads as glass
        ShapePath {
            strokeWidth: -1
            fillGradient: LinearGradient {
                x1: hl.wheel.c; y1: hl.wheel.c - hl.wheel.outerR
                x2: hl.wheel.c; y2: hl.wheel.c - hl.wheel.innerR
                GradientStop { position: 0.0; color: hl.theme.hotSheen }
                GradientStop { position: 0.6; color: hl.theme.sheenClear }
            }
            PathSvg { path: hl.wheel.wedgePath }
        }
    }
}
