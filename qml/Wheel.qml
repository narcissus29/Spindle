import QtQuick
import QtQuick.Shapes

// The ring of wedges, the gliding highlight, the center pill, the rim
// buttons (pin, close), hit-testing and the wheel-switch animation.
//
// Performance rules followed here:
// - Wedge geometry is built once per wheel (when the wedge count changes).
//   Every animation changes only rotation / scale / opacity, never a path,
//   so nothing is re-tessellated while animating.
// - Hit-testing is plain math in JS, run on each drag / mouse move. Python
//   is not called per move.
Item {
    id: wheelRoot

    required property QtObject theme
    property bool active: false       // window shown; when false, swaps are instant
    property bool dragging: false

    property var options: []          // what is drawn (lags bridge.options during a switch)
    readonly property int count: options.length
    readonly property real c: width / 2
    readonly property real outerR: c * 0.86
    readonly property real innerR: outerR * 0.40
    readonly property real hubR: innerR - gapPx
    readonly property real gapPx: Math.max(2, width * 0.008)
    readonly property real step: count > 0 ? 360 / count : 360
    readonly property bool dimmed: bridge.idle || bridge.refused

    // One wedge pointing straight up; each delegate rotates it into place.
    readonly property string wedgePath: buildWedge(outerR, innerR)
    readonly property string rimPath: buildRim(outerR - 1.2)

    property int hoveredIndex: -1
    property bool overCenter: false
    property bool cancelHover: false     // pointer on the hub while a job runs
    property bool animateEntry: false
    property real lastX: -1
    property real lastY: -1

    readonly property int hitCenter: -2
    readonly property int hitNone: -1

    // ------------------------------------------------------------ geometry

    function _pt(r, a) {
        return (c + r * Math.sin(a)).toFixed(3) + " " + (c - r * Math.cos(a)).toFixed(3)
    }

    // A full circle as two half arcs (SVG can't draw a 360° arc in one go).
    function _circle(r, sweep) {
        return "M " + (c + r) + " " + c
             + " A " + r + " " + r + " 0 1 " + sweep + " " + (c - r) + " " + c
             + " A " + r + " " + r + " 0 1 " + sweep + " " + (c + r) + " " + c + " Z"
    }

    function buildWedge(R, r) {
        if (count === 0)
            return ""
        // One option: a seamless full ring (outer circle with the inner one
        // cut out; ShapePath's default odd-even fill makes the hole).
        if (count === 1)
            return _circle(R, 1) + " " + _circle(r, 0)
        // Constant-width gaps: the angular gap is larger on the inner arc.
        const half = step / 2 * Math.PI / 180
        const ho = half - (gapPx / 2) / R
        const hi = half - (gapPx / 2) / r
        const large = 2 * ho > Math.PI ? 1 : 0
        return "M " + _pt(R, -ho)
             + " A " + R + " " + R + " 0 " + large + " 1 " + _pt(R, ho)
             + " L " + _pt(r, hi)
             + " A " + r + " " + r + " 0 " + large + " 0 " + _pt(r, -hi)
             + " Z"
    }

    function buildRim(R) {
        if (count === 0)
            return ""
        if (count === 1)
            return _circle(R, 1)
        const ho = step / 2 * Math.PI / 180 - (gapPx / 2 + 2) / R
        return "M " + _pt(R, -ho) + " A " + R + " " + R + " 0 0 1 " + _pt(R, ho)
    }

    // --------------------------------------------------------- hit-testing

    function insideRing(x, y) {
        const dx = x - c, dy = y - c
        return dx * dx + dy * dy <= outerR * outerR
    }

    // The rim band a pinned wheel is dragged by: the outer edge of the
    // wedges plus the glow just outside it (not the rim buttons).
    readonly property real rimIn: outerR - Math.max(8, width * 0.025)
    readonly property real rimOut: outerR + width * 0.04
    function onRim(x, y) {
        if (pinButton.hit(x, y) || closeButton.hit(x, y))
            return false
        const dx = x - c, dy = y - c, r2 = dx * dx + dy * dy
        return r2 >= rimIn * rimIn && r2 <= rimOut * rimOut
    }

    // Wedge index under (x, y), hitCenter for the hub, or hitNone.
    function hitTest(x, y) {
        if (pinButton.hit(x, y) || closeButton.hit(x, y))
            return hitNone
        const dx = x - c, dy = y - c
        const r = Math.sqrt(dx * dx + dy * dy)
        if (r < innerR)
            return hitCenter
        if (r > outerR * 1.12 || count === 0 || dimmed)
            return hitNone
        let a = Math.atan2(dy, dx) * 180 / Math.PI + 90 + step / 2
        a = ((a % 360) + 360) % 360
        return Math.min(count - 1, Math.floor(a / step))
    }

    function track(x, y) {
        lastX = x
        lastY = y
        const hit = hitTest(x, y)
        overCenter = hit === hitCenter
        setHover(hit >= 0 ? hit : -1)
    }

    function setHover(i) {
        if (i === hoveredIndex)
            return
        highlight.moveTo(i, hoveredIndex >= 0)
        hoveredIndex = i
    }

    function endDrag() {
        dragging = false
        clearHover()
    }

    function clearHover() {
        cancelHover = false
        setHover(-1)
        overCenter = false
        lastX = lastY = -1
    }

    function reset() {
        endDrag()
        exitAnim.stop()
        ring.opacity = 1
        ring.scale = 1
    }

    // ------------------------------------------------------- wheel switching

    Component.onCompleted: options = bridge.options

    Connections {
        target: bridge
        function onOptionsChanged() { wheelRoot.applyOptions() }
    }

    function applyOptions() {
        if (!active || theme.reduced || count === 0)
            swapOptions(false)
        else
            exitAnim.restart()
    }

    // A drop or click must be read against the wedges the bridge has, not
    // the outgoing ones still fading out mid-switch: finish any switch
    // instantly and re-check what is under the pointer.
    function settle() {
        if (exitAnim.running) {
            exitAnim.stop()
            swapOptions(false)
        }
        if (lastX >= 0)
            track(lastX, lastY)
    }

    function swapOptions(animate) {
        highlight.fade = false
        setHover(-1)
        highlight.fade = true
        animateEntry = animate
        options = bridge.options      // Repeaters rebuild; new wedges run their entry
        ring.opacity = 1
        ring.scale = 1
        if ((dragging || bridge.parked) && lastX >= 0)
            track(lastX, lastY)
    }

    ParallelAnimation {
        id: exitAnim
        OpacityAnimator {
            target: ring; to: 0
            duration: wheelRoot.theme.exitMs; easing.type: Easing.OutCubic
        }
        ScaleAnimator {
            target: ring; to: 0.96
            duration: wheelRoot.theme.exitMs; easing.type: Easing.OutCubic
        }
        onFinished: wheelRoot.swapOptions(true)
    }

    // ------------------------------------------------------------- visuals

    // Soft shadow under the ring (static).
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeWidth: -1
            fillGradient: RadialGradient {
                centerX: wheelRoot.c; centerY: wheelRoot.c + wheelRoot.outerR * 0.03
                centerRadius: wheelRoot.outerR * 1.12
                focalX: centerX; focalY: centerY
                GradientStop { position: 0.70; color: wheelRoot.theme.shadowClear }
                GradientStop { position: 0.86; color: wheelRoot.theme.shadow }
                GradientStop { position: 1.00; color: wheelRoot.theme.shadowClear }
            }
            PathAngleArc {
                centerX: wheelRoot.c; centerY: wheelRoot.c + wheelRoot.outerR * 0.03
                radiusX: wheelRoot.outerR * 1.12; radiusY: radiusX
                startAngle: 0; sweepAngle: 360
            }
        }
    }

    // Pinned: a soft glow just outside the rim (static path, fades in/out).
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        opacity: bridge.pinned ? 1 : 0
        visible: opacity > 0
        Behavior on opacity {
            NumberAnimation { duration: wheelRoot.theme.d(wheelRoot.theme.switchMs); easing.type: Easing.OutCubic }
        }
        ShapePath {
            fillColor: "transparent"
            strokeColor: wheelRoot.theme.glow
            strokeWidth: wheelRoot.width * 0.026
            PathAngleArc {
                centerX: wheelRoot.c; centerY: wheelRoot.c
                radiusX: wheelRoot.outerR + 1; radiusY: radiusX
                startAngle: 0; sweepAngle: 360
            }
        }
        ShapePath {
            fillColor: "transparent"
            strokeColor: wheelRoot.theme.glow
            strokeWidth: wheelRoot.width * 0.010
            PathAngleArc {
                centerX: wheelRoot.c; centerY: wheelRoot.c
                radiusX: wheelRoot.outerR + 1; radiusY: radiusX
                startAngle: 0; sweepAngle: 360
            }
        }
    }

    Item {
        id: ring
        anchors.fill: parent

        Item {
            anchors.fill: parent
            opacity: wheelRoot.dimmed ? 0.7 : 1.0
            Behavior on opacity { NumberAnimation { duration: wheelRoot.theme.d(200); easing.type: Easing.OutCubic } }

            Repeater {
                model: wheelRoot.options
                delegate: Wedge { wheel: wheelRoot; theme: wheelRoot.theme }
            }

            Highlight {
                id: highlight
                anchors.fill: parent
                wheel: wheelRoot
                theme: wheelRoot.theme
            }

            Repeater {
                model: wheelRoot.options
                delegate: WedgeLabel { wheel: wheelRoot; theme: wheelRoot.theme }
            }
        }
    }

    CenterPill {
        objectName: "centerPill"
        anchors.centerIn: parent
        theme: wheelRoot.theme
        hubR: wheelRoot.hubR
        parked: bridge.parked
        thumbSource: bridge.parkedThumb
        firstLabel: bridge.firstLabel
        count: bridge.fileCount
        danger: wheelRoot.cancelHover && bridge.busy
        warn: bridge.statusWarn && !bridge.busy && wheelRoot.hoveredIndex < 0 && !wheelRoot.dragging
        entry: bridge.customEntry
        lastSize: bridge.lastCustom
        canClear: bridge.parked && !bridge.customEntry && !wheelRoot.dragging
        onEntryAccepted: (size) => entryError = bridge.runCustom(size)
        onEntryCanceled: bridge.leaveSubRing()
        onClearClicked: bridge.clearStack()
        text: {
            if (bridge.customEntry)
                return ""
            if (wheelRoot.cancelHover && bridge.busy)
                return "Cancel"
            if (wheelRoot.hoveredIndex >= 0 && wheelRoot.hoveredIndex < wheelRoot.count)
                return wheelRoot.options[wheelRoot.hoveredIndex].name
            if (bridge.subRing !== "")
                return bridge.subRingTitle            // "Compress to…"
            if (bridge.refused)
                return bridge.refusedText         // "Not supported", "Mixed files"
            if (wheelRoot.dragging)
                return bridge.formatLabel         // over parked files: all of them ("4 JPGs")
            if (bridge.parked)
                return bridge.canSwitch ? "Scroll to switch" : bridge.formatLabel
            if (bridge.statusText !== "")
                return bridge.statusText          // "3/10", "Done"
            if (bridge.idle)
                return "Drop a file"
            return bridge.formatLabel
        }
    }

    // Something runs: a ring just inside the hub's edge fills with the
    // current file's progress (spins while that can't be told).
    ProgressRing {
        objectName: "progressRing"
        anchors.centerIn: parent
        theme: wheelRoot.theme
        thickness: Math.max(3, wheelRoot.hubR * 0.065)
        radius: wheelRoot.hubR - thickness / 2 - 2
        running: bridge.busy
        progress: bridge.progress
        animate: wheelRoot.active
    }

    // ---- rim buttons ----

    RimButton {
        id: pinButton
        wheel: wheelRoot
        theme: wheelRoot.theme
        angleDeg: 45
        active: bridge.pinned
        iconPath: "M8.5 3.5h7 M10 3.5v5.5l-3 3.5h10l-3-3.5V3.5 M12 12.5v8"
        fillPath: "M10 3.5h4v5.5l3 3.5H7l3-3.5z"
        onClicked: bridge.togglePin()
    }

    RimButton {
        id: closeButton
        wheel: wheelRoot
        theme: wheelRoot.theme
        angleDeg: 59
        shown: bridge.pinned || bridge.dropZone
        iconPath: "M8 8l8 8 M16 8l-8 8"
        onClicked: bridge.dismiss()
    }
}
