import QtQuick

// Root of the wheel window. Owns the open/close animation, keyboard input,
// the drop area and moving a pinned wheel; everything visual lives in
// Wheel.qml.
Item {
    id: root
    focus: true

    property bool shown: false

    Theme { id: theme; reduced: bridge.reduceAnimations; name: bridge.themeName }

    // ---- where the wheel sits ----
    // Overlay mode (Wayland): the window covers the screen and the wheel is
    // drawn inside it, centered unless a pinned wheel was moved. In
    // small-window mode the window itself moves (Python) and the wheel
    // always fills it, so `centered` stays true there.
    property bool centered: true
    property real px: 0
    property real py: 0
    readonly property real wheelCx: centered ? width / 2 : px
    readonly property real wheelCy: centered ? height / 2 : py
    readonly property real snapMargin: 8

    function placeAt(x, y) {
        glideAnim.stop()
        centered = false
        px = x
        py = y
    }

    function glideTo(x, y, remember) {
        if (centered) {
            px = wheelCx
            py = wheelCy
            centered = false
        }
        glideAnim.stop()
        glideX.to = x
        glideY.to = y
        glideAnim.start()
        // The input region jumps straight to the end point; the pointer is
        // not over it mid-glide anyway.
        bridge.wheelMoved(x, y, x / width, y / height, remember)
    }

    function clamped(x, y) {
        const half = wheel.width / 2
        return Qt.point(Math.min(Math.max(x, half + snapMargin), width - half - snapMargin),
                        Math.min(Math.max(y, half + snapMargin), height - half - snapMargin))
    }

    // Clamp onto the screen, then push to the nearest edge.
    function snapped(x, y) {
        const half = wheel.width / 2
        const l = half + snapMargin, r = width - half - snapMargin
        const t = half + snapMargin, b = height - half - snapMargin
        const p = clamped(x, y)
        const gl = p.x - l, gr = r - p.x, gt = p.y - t, gb = b - p.y
        const g = Math.min(gl, gr, gt, gb)
        if (g === gl) p.x = l
        else if (g === gr) p.x = r
        else if (g === gt) p.y = t
        else p.y = b
        return p
    }

    ParallelAnimation {
        id: glideAnim
        NumberAnimation {
            id: glideX
            target: root; property: "px"
            duration: theme.d(280); easing.type: Easing.OutCubic
        }
        NumberAnimation {
            id: glideY
            target: root; property: "py"
            duration: theme.d(280); easing.type: Easing.OutCubic
        }
    }

    // Clicks outside the ring dismiss (unless pinned or a drop zone; on
    // Wayland their input region excludes the outside anyway). While files are
    // parked it also does hover, click-to-run and scroll-to-switch. A pinned
    // wheel can be dragged by its rim. Declared before the wheel so it sits
    // underneath it.
    MouseArea {
        id: background
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton  // right-click: back from a sub-ring
        hoverEnabled: bridge.parked || bridge.pinned || bridge.busy
        cursorShape: moving ? Qt.ClosedHandCursor
                   : overRim ? Qt.OpenHandCursor
                   : (bridge.parked && wheel.hoveredIndex >= 0) || (wheel.cancelHover && bridge.busy) ? Qt.PointingHandCursor
                   : Qt.ArrowCursor
        property real scrollAccum: 0
        property double lastSwitch: 0

        // rim drag state
        property bool overRim: false
        property bool rimPressed: false
        property bool moving: false
        property bool justMoved: false
        property point pressGlobal
        property real startX: 0
        property real startY: 0

        onPressed: (mouse) => {
            const p = mapToItem(wheel, mouse.x, mouse.y)
            rimPressed = mouse.button === Qt.LeftButton && bridge.pinned && wheel.onRim(p.x, p.y)
            moving = false
            justMoved = false
            if (rimPressed) {
                pressGlobal = mapToGlobal(mouse.x, mouse.y)
                startX = root.wheelCx
                startY = root.wheelCy
            }
        }

        onPositionChanged: (mouse) => {
            if (rimPressed) {
                const g = mapToGlobal(mouse.x, mouse.y)
                const dx = g.x - pressGlobal.x, dy = g.y - pressGlobal.y
                if (!moving) {
                    if (dx * dx + dy * dy < 25)
                        return              // not a drag yet: could still be a click
                    moving = true
                    wheel.clearHover()
                    if (!bridge.overlay)
                        bridge.moveWindow("start", 0, 0)
                }
                if (bridge.overlay)
                    root.placeAt(startX + dx, startY + dy)
                else
                    bridge.moveWindow("move", dx, dy)
                return
            }
            const p = mapToItem(wheel, mouse.x, mouse.y)
            overRim = bridge.pinned && wheel.onRim(p.x, p.y)
            if (overRim)
                wheel.clearHover()
            else if (bridge.parked)
                wheel.track(p.x, p.y)
            wheel.cancelHover = bridge.busy && wheel.hitTest(p.x, p.y) === wheel.hitCenter
        }

        function endMove() {
            if (moving) {
                if (bridge.overlay) {
                    const t = root.snapped(root.wheelCx, root.wheelCy)
                    root.glideTo(t.x, t.y, true)
                } else {
                    bridge.moveWindow("end", 0, 0)
                }
            }
            justMoved = moving
            moving = false
            rimPressed = false
        }
        onReleased: endMove()
        onCanceled: endMove()

        onExited: {
            overRim = false
            wheel.cancelHover = false
            if (bridge.parked)
                wheel.clearHover()
        }

        onClicked: (mouse) => {
            if (justMoved) {          // the end of a rim drag, not a click
                justMoved = false
                return
            }
            const p = mapToItem(wheel, mouse.x, mouse.y)
            if (mouse.button === Qt.RightButton) {
                if (bridge.subRing !== "")
                    bridge.leaveSubRing()
                return
            }
            if (bridge.subRing !== "" && wheel.hitTest(p.x, p.y) === wheel.hitCenter) {
                bridge.leaveSubRing()  // the center goes back
                return
            }
            if (bridge.busy && wheel.hitTest(p.x, p.y) === wheel.hitCenter) {
                bridge.cancel()       // the pill reads "Cancel" while busy
                return
            }
            if (bridge.pinned && wheel.onRim(p.x, p.y))
                return                // the rim is a handle, not a wedge
            if (bridge.parked) {
                wheel.settle()
                const hit = wheel.hitTest(p.x, p.y)
                if (hit >= 0) {
                    bridge.activate(hit)
                    return
                }
            }
            if (!wheel.insideRing(p.x, p.y) && !bridge.pinned && !bridge.dropZone)
                bridge.dismiss()
        }
        onWheel: (ev) => {
            // Touchpads send many small deltas; act once per notch-worth.
            scrollAccum += ev.angleDelta.y !== 0 ? ev.angleDelta.y : ev.angleDelta.x
            if (Math.abs(scrollAccum) < 120)
                return
            scrollAccum = 0
            const now = Date.now()
            if (now - lastSwitch > 300) {
                lastSwitch = now
                bridge.switchWheel()
            }
        }
    }

    Wheel {
        id: wheel
        objectName: "wheel"
        theme: theme
        active: root.shown
        width: bridge.wheelSize
        height: width
        x: Math.round(root.wheelCx - width / 2)
        y: Math.round(root.wheelCy - height / 2)
        opacity: 0
        scale: 0.85
    }

    DropArea {
        anchors.fill: parent

        onEntered: (drag) => {
            const urls = []
            for (let i = 0; i < drag.urls.length; ++i)
                urls.push(drag.urls[i].toString())
            const ok = bridge.dragEnter(urls)
            if (ok) {
                // Always Copy: accepting a Move would let the file manager
                // delete the original after the drop.
                drag.accept(Qt.CopyAction)
                wheel.dragging = true
                const p = mapToItem(wheel, drag.x, drag.y)
                wheel.track(p.x, p.y)
            } else {
                drag.accepted = false
            }
        }
        onPositionChanged: (drag) => {
            const p = mapToItem(wheel, drag.x, drag.y)
            wheel.track(p.x, p.y)
        }
        onExited: {
            wheel.endDrag()
            bridge.dragLeave()
        }
        onDropped: (drop) => {
            // Center parks the file; a wedge runs straight away.
            wheel.settle()
            const onCenter = wheel.overCenter
            const index = wheel.hoveredIndex
            wheel.endDrag()
            if (onCenter ? bridge.park() : bridge.drop(index))
                drop.accept(Qt.CopyAction)
            else
                drop.accepted = false
        }
    }

    Keys.onPressed: (ev) => {
        if (ev.key === Qt.Key_Escape) {
            if (bridge.subRing !== "")
                bridge.leaveSubRing()     // back to the wheel first
            else
                bridge.dismiss()
            ev.accepted = true
        } else if (ev.key === Qt.Key_Tab || ev.key === Qt.Key_Backtab) {
            bridge.switchWheel()
            ev.accepted = true
        }
    }

    // Animators run on the render thread: they keep going even if Python
    // is busy on the UI thread.
    ParallelAnimation {
        id: openAnim
        ScaleAnimator {
            target: wheel; to: 1.0
            duration: theme.openMs
            easing.type: Easing.OutBack; easing.overshoot: 1.3
        }
        OpacityAnimator {
            target: wheel; to: 1.0
            duration: theme.openMs * 0.8
            easing.type: Easing.OutCubic
        }
    }

    ParallelAnimation {
        id: closeAnim
        ScaleAnimator {
            target: wheel; to: 0.85
            duration: theme.closeMs
            easing.type: Easing.InCubic
        }
        OpacityAnimator {
            target: wheel; to: 0.0
            duration: theme.closeMs
            easing.type: Easing.InCubic
        }
        onFinished: root.finishClose()
    }

    function finishClose() {
        wheel.reset()
        bridge.closeFinished()
    }

    Connections {
        target: bridge

        function onOpenRequested() {
            closeAnim.stop()
            if (!bridge.pinned) {     // unpinned always opens centered
                glideAnim.stop()
                root.centered = true
            }
            root.shown = true
            root.forceActiveFocus()
            if (theme.reduced) {
                wheel.scale = 1.0
                wheel.opacity = 1.0
            } else if (wheel.opacity < 1.0 || wheel.scale !== 1.0) {
                openAnim.restart()
            }
        }

        function onCloseRequested() {
            openAnim.stop()
            root.shown = false
            wheel.endDrag()
            if (theme.reduced) {
                wheel.scale = 0.85
                wheel.opacity = 0.0
                root.finishClose()
            } else {
                closeAnim.restart()
            }
        }

        // Typing a custom size ended: keys go to the wheel again.
        function onStateChanged() {
            if (!bridge.customEntry && root.shown && !root.activeFocus)
                root.forceActiveFocus()
        }

        // Clicking a wedge on parked files starts the run and unparks; drop
        // the leftover hover so the pill shows progress, not the wedge name.
        function onParkedChanged(parked) {
            if (!parked && !wheel.dragging)
                wheel.clearHover()
        }

        // Overlay mode: pinning moves the wheel to the remembered spot.
        function onPinnedChanged(pinned) {
            if (!bridge.overlay || !pinned)
                return
            // No saved spot: the wheel stays where it is. (Python keeps the
            // input region on it; while centered that follows the window
            // size, so nothing is reported from here.)
            const s = bridge.pinnedSpot
            if (s.x >= 0 && s.y >= 0) {
                const t = root.clamped(s.x * root.width, s.y * root.height)
                root.glideTo(t.x, t.y, false)
            }
        }
    }
}
