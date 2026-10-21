import QtQuick
import QtQuick.Shapes

// A ring just inside the hub's edge while something runs. It fills with
// the current file's progress (0..1); while that can't be told (-1: a
// library loading, a document being analysed) a short arc spins instead.
// When the run ends it fills up and fades out.
//
// Cost: nothing while hidden. The spinner turns with a RotationAnimator
// (render thread, no path rebuilt per frame) and only runs while it is
// shown; the filling arc is rebuilt only when the progress changes
// (at most ~10 times a second, eased in between).
Item {
    id: ring

    required property QtObject theme
    property real radius: 50          // center line of the ring
    property real thickness: 4
    property bool running: false      // something is running: show the ring
    property real progress: -1        // current file 0..1, -1 = can't tell
    property bool animate: true       // the window is shown

    readonly property bool unknown: running && progress < 0
    // What the arc shows. Grows with an ease; going back (the next file
    // of a batch) is instant.
    property real shown: 0

    width: (radius + thickness) * 2
    height: width
    opacity: running ? 1 : 0
    visible: opacity > 0.01
    Behavior on opacity {
        NumberAnimation { duration: ring.theme.d(ring.running ? ring.theme.fadeMs : 420); easing.type: Easing.OutCubic }
    }

    function moveTo(v) {
        if (v < shown || theme.reduced) {
            grow.stop()
            shown = v
        } else if (v !== grow.to || !grow.running) {
            grow.to = v
            grow.restart()
        }
    }
    onProgressChanged: if (running) moveTo(Math.max(0, progress))
    onRunningChanged: moveTo(running ? Math.max(0, progress) : 1)  // done: fill up while fading

    NumberAnimation {
        id: grow
        target: ring
        property: "shown"
        duration: 260
        easing.type: Easing.OutCubic
    }

    // the track
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            fillColor: "transparent"
            strokeColor: Qt.alpha(ring.theme.hotOuter, 0.16)
            strokeWidth: ring.thickness
            PathAngleArc {
                centerX: ring.width / 2; centerY: ring.height / 2
                radiusX: ring.radius; radiusY: ring.radius
                startAngle: 0; sweepAngle: 360
            }
        }
    }

    // the progress
    Shape {
        objectName: "progressArc"
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        opacity: ring.unknown ? 0 : 1
        visible: opacity > 0.01 && ring.shown > 0.002
        Behavior on opacity { NumberAnimation { duration: ring.theme.d(ring.theme.fadeMs) } }
        ShapePath {
            fillColor: "transparent"
            strokeColor: ring.theme.hotOuter
            strokeWidth: ring.thickness
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: ring.width / 2; centerY: ring.height / 2
                radiusX: ring.radius; radiusY: ring.radius
                startAngle: -90
                sweepAngle: 360 * Math.min(1, ring.shown)
            }
        }
    }

    // can't tell: a spinning arc
    Shape {
        id: spinner
        objectName: "progressSpinner"
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        opacity: ring.unknown ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: ring.theme.d(ring.theme.fadeMs) } }
        ShapePath {
            fillColor: "transparent"
            strokeColor: ring.theme.hotOuter
            strokeWidth: ring.thickness
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: ring.width / 2; centerY: ring.height / 2
                radiusX: ring.radius; radiusY: ring.radius
                startAngle: -90; sweepAngle: 80
            }
        }
        RotationAnimator {
            target: spinner
            from: 0; to: 360
            duration: 1100
            loops: Animation.Infinite
            running: spinner.visible && ring.animate && !ring.theme.reduced
        }
    }
}
