import QtQuick
import QtQuick.Shapes

// Small round glass button sitting on the wheel's rim (pin, close).
// `active` fills it with the highlight gradient and turns the icon white.
Item {
    id: btn

    required property Item wheel
    required property QtObject theme
    property real angleDeg: 45        // position on the rim, clockwise from the top
    property string iconPath: ""      // 24x24 stroke path
    property string fillPath: ""      // optional 24x24 path filled when active
    property bool active: false
    property bool shown: true
    signal clicked()

    readonly property real size: Math.round(wheel.width * 0.066)
    readonly property real _a: angleDeg * Math.PI / 180
    readonly property real cx: wheel.c + wheel.outerR * Math.sin(_a)
    readonly property real cy: wheel.c - wheel.outerR * Math.cos(_a)

    // For the wheel's hit-testing: hovering / dropping on a button must not
    // highlight the wedge underneath.
    function hit(px, py) {
        const r = size / 2 + 3
        return shown && (px - cx) * (px - cx) + (py - cy) * (py - cy) <= r * r
    }

    width: size
    height: size
    x: cx - width / 2
    y: cy - height / 2

    opacity: shown ? 1 : 0
    visible: opacity > 0
    scale: (shown ? 1.0 : 0.6) * (mouse.containsMouse ? 1.12 : 1.0)
    Behavior on opacity {
        NumberAnimation { duration: btn.theme.d(btn.theme.fadeMs); easing.type: Easing.OutCubic }
    }
    Behavior on scale {
        NumberAnimation { duration: btn.theme.d(btn.theme.hoverMs); easing.type: Easing.OutBack }
    }

    readonly property color ink: active ? theme.inkHot : theme.ink
    Rectangle {
        anchors.fill: parent
        radius: width / 2
        border.color: btn.active ? btn.theme.hotEdge : btn.theme.edge
        border.width: 1
        gradient: Gradient {
            GradientStop {
                position: 0.0
                color: btn.active ? btn.theme.hotInner : btn.theme.pillTop
                Behavior on color { ColorAnimation { duration: btn.theme.d(btn.theme.fadeMs); easing.type: Easing.OutCubic } }
            }
            GradientStop {
                position: 1.0
                color: btn.active ? btn.theme.hotOuter : btn.theme.pillBottom
                Behavior on color { ColorAnimation { duration: btn.theme.d(btn.theme.fadeMs); easing.type: Easing.OutCubic } }
            }
        }
    }

    Item {
        anchors.centerIn: parent
        width: Math.round(btn.size * 0.62)
        height: width

        Shape {
            width: 24
            height: 24
            scale: parent.width / 24
            transformOrigin: Item.TopLeft
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeWidth: -1
                fillColor: btn.active && btn.fillPath !== "" ? btn.ink : "transparent"
                PathSvg { path: btn.fillPath }
            }
            ShapePath {
                fillColor: "transparent"
                strokeColor: btn.ink
                strokeWidth: 2
                capStyle: ShapePath.RoundCap
                joinStyle: ShapePath.RoundJoin
                PathSvg { path: btn.iconPath }
            }
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        enabled: btn.shown
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: btn.clicked()
    }
}
