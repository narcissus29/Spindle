import QtQuick
import QtQuick.Shapes

// Icon + label for one wedge. Positioned (not rotated) so text stays upright.
// Drawn above the highlight; turns white when its wedge is hovered.
Item {
    id: lbl

    required property int index
    required property var modelData
    required property Item wheel
    required property QtObject theme

    readonly property bool hasIcon: modelData.icon !== ""
    readonly property bool hovered: wheel.hoveredIndex === index
    readonly property real angle: index * wheel.step * Math.PI / 180

    // Follows the wedge's 1.04 hover scale (which is about the wheel center).
    property real lift: hovered ? theme.hoverScale : 1.0
    Behavior on lift {
        NumberAnimation { duration: lbl.theme.d(lbl.theme.hoverMs); easing.type: Easing.OutBack }
    }

    property color ink: hovered ? theme.inkHot : theme.ink
    Behavior on ink { ColorAnimation { duration: lbl.theme.d(lbl.theme.fadeMs); easing.type: Easing.OutCubic } }

    readonly property real radius: (wheel.innerR + wheel.outerR) / 2 * lift
    x: wheel.c + radius * Math.sin(angle) - width / 2
    y: wheel.c - radius * Math.cos(angle) - height / 2
    width: col.implicitWidth
    height: col.implicitHeight

    Component.onCompleted: {
        if (wheel.animateEntry) {
            opacity = 0
            scale = 0.6
            enter.start()
        }
    }

    SequentialAnimation {
        id: enter
        PauseAnimation { duration: 40 + lbl.index * lbl.theme.staggerMs }
        ParallelAnimation {
            ScaleAnimator {
                target: lbl; to: 1
                duration: lbl.theme.switchMs; easing.type: Easing.OutBack
            }
            OpacityAnimator {
                target: lbl; to: 1
                duration: lbl.theme.switchMs * 0.7; easing.type: Easing.OutCubic
            }
        }
    }

    Column {
        id: col
        spacing: lbl.wheel.width * 0.008

        Item {
            visible: lbl.hasIcon
            width: Math.round(lbl.wheel.width * 0.068)
            height: width
            anchors.horizontalCenter: parent.horizontalCenter

            // Icons are 24x24 stroke paths from assets/icons/*.svg.
            Shape {
                width: 24
                height: 24
                scale: parent.width / 24
                transformOrigin: Item.TopLeft
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    fillColor: "transparent"
                    strokeColor: lbl.ink
                    strokeWidth: 1.9
                    capStyle: ShapePath.RoundCap
                    joinStyle: ShapePath.RoundJoin
                    PathSvg { path: lbl.modelData.icon }
                }
            }
        }

        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            anchors.horizontalCenter: parent.horizontalCenter
            text: lbl.modelData.name
            color: lbl.ink
            font.pixelSize: Math.round(lbl.wheel.width * (lbl.hasIcon ? 0.034 : 0.050))
            font.weight: lbl.hasIcon ? Font.DemiBold : Font.Bold
            font.letterSpacing: lbl.hasIcon ? 0 : 0.5
        }
    }
}
