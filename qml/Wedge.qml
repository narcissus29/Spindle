import QtQuick
import QtQuick.Shapes

// The frosted-glass body of one wedge. All wedges share one path (pointing
// up); this item rotates it into place. Icon and label are in WedgeLabel.qml
// so they can sit above the hover highlight.
Item {
    id: w

    required property int index
    required property var modelData
    required property Item wheel
    required property QtObject theme

    readonly property real baseAngle: index * wheel.step
    readonly property bool hovered: wheel.hoveredIndex === index

    // Fake "frosted glass" lighting: a sheen that always comes from the
    // top-left of the wheel, whatever this wedge's rotation. The gradient is
    // computed once from baseAngle, in this wedge's rotated coordinates.
    readonly property real _a: -baseAngle * Math.PI / 180
    readonly property real _lx: -0.7071 * Math.cos(_a) + 0.7071 * Math.sin(_a)
    readonly property real _ly: -0.7071 * Math.sin(_a) - 0.7071 * Math.cos(_a)

    width: wheel.width
    height: wheel.height

    Component.onCompleted: {
        if (wheel.animateEntry) {
            rotation = baseAngle - theme.swingDeg
            opacity = 0
            enter.start()
        } else {
            rotation = baseAngle
        }
    }

    SequentialAnimation {
        id: enter
        PauseAnimation { duration: w.index * w.theme.staggerMs }
        ParallelAnimation {
            RotationAnimator {
                target: w; to: w.baseAngle
                duration: w.theme.switchMs; easing.type: Easing.OutCubic
            }
            OpacityAnimator {
                target: w; to: 1
                duration: w.theme.switchMs * 0.7; easing.type: Easing.OutCubic
            }
        }
    }

    Item {
        anchors.fill: parent
        scale: w.hovered ? w.theme.hoverScale : 1.0
        Behavior on scale {
            NumberAnimation { duration: w.theme.d(w.theme.hoverMs); easing.type: Easing.OutBack }
        }

        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer

            // body: lighter near the hub, deeper at the rim
            ShapePath {
                strokeColor: w.theme.edge
                strokeWidth: 1
                joinStyle: ShapePath.RoundJoin
                fillGradient: RadialGradient {
                    centerX: w.wheel.c; centerY: w.wheel.c
                    centerRadius: w.wheel.outerR
                    focalX: w.wheel.c; focalY: w.wheel.c
                    GradientStop { position: w.wheel.innerR / w.wheel.outerR; color: w.theme.glassInner }
                    GradientStop { position: 1.0; color: w.theme.glassOuter }
                }
                PathSvg { path: w.wheel.wedgePath }
            }

            // sheen
            ShapePath {
                strokeWidth: -1
                fillGradient: LinearGradient {
                    x1: w.wheel.c + w._lx * w.wheel.outerR; y1: w.wheel.c + w._ly * w.wheel.outerR
                    x2: w.wheel.c - w._lx * w.wheel.outerR; y2: w.wheel.c - w._ly * w.wheel.outerR
                    GradientStop { position: 0.0; color: w.theme.sheen }
                    GradientStop { position: 0.55; color: w.theme.sheenClear }
                }
                PathSvg { path: w.wheel.wedgePath }
            }

            // bright outer rim
            ShapePath {
                fillColor: "transparent"
                strokeColor: w.theme.rim
                strokeWidth: 1.6
                capStyle: ShapePath.RoundCap
                PathSvg { path: w.wheel.rimPath }
            }
        }
    }
}
