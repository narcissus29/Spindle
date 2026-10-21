import QtQuick
import "."

// Crop rectangle over the whole page: shading outside, handles on the
// corners and edges, rule-of-thirds lines while dragging.
// Drag inside to move it, a handle to resize, or outside it to draw a new
// one. The rectangle lives here while dragging and is committed on release
// (one undo step). Aspect presets keep the ratio while resizing.
Item {
    id: ov

    required property Item vp

    readonly property real sx: vp.stageX
    readonly property real sy: vp.stageY
    readonly property real sw: Math.max(1, vp.stagePxW)
    readonly property real sh: Math.max(1, vp.stagePxH)

    property bool dragging: false
    property rect dragRect: Qt.rect(0, 0, 1, 1)
    readonly property rect r: dragging ? dragRect : vp.crop  // normalized, in the displayed page

    readonly property real x0: sx + r.x * sw
    readonly property real y0: sy + r.y * sh
    readonly property real x1: sx + (r.x + r.width) * sw
    readonly property real y1: sy + (r.y + r.height) * sh

    visible: opacity > 0
    opacity: vp.cropping && !vp.turning ? vp.reveal : 0
    Behavior on opacity { NumberAnimation { duration: Style.d(Style.fadeMs); easing.type: Easing.OutCubic } }
    enabled: vp.cropping && !vp.turning

    // ---- aspect ratio ----

    // target width / height in content units (pixels or points)
    readonly property real targetRatio: {
        let ratio = 0
        if (vp.aspect === "original") ratio = vp.stageW / vp.stageH
        else if (vp.aspect === "1:1") ratio = 1
        else if (vp.aspect === "4:3") ratio = 4 / 3
        else if (vp.aspect === "16:9") ratio = 16 / 9
        else if (vp.aspect === "exact" && editor.outputHeight > 0) return editor.outputWidth / editor.outputHeight
        if (ratio > 0 && vp.portrait && vp.aspect !== "1:1") ratio = 1 / ratio
        return ratio
    }
    // the same ratio for normalized rects
    readonly property real normRatio: targetRatio > 0 ? targetRatio * vp.stageH / vp.stageW : 0

    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)) }

    // Largest rect of the preset's ratio inside the current one, same center.
    function applyAspect() {
        if (normRatio <= 0) return
        const c = vp.crop
        let w = c.width, h = c.height
        if (w / h > normRatio) w = h * normRatio
        else h = w / normRatio
        const x = clamp(c.x + (c.width - w) / 2, 0, 1 - w)
        const y = clamp(c.y + (c.height - h) / 2, 0, 1 - h)
        editor.setCrop(x, y, w, h)
    }

    // ---- dragging ----

    readonly property real minW: 16 / sw
    readonly property real minH: 16 / sh

    function zoneAt(px, py) {
        const t = 12
        const inX = px > x0 - t && px < x1 + t, inY = py > y0 - t && py < y1 + t
        const nl = Math.abs(px - x0) <= t, nr = Math.abs(px - x1) <= t
        const nt = Math.abs(py - y0) <= t, nb = Math.abs(py - y1) <= t
        if (nl && nt) return "tl"
        if (nr && nt) return "tr"
        if (nl && nb) return "bl"
        if (nr && nb) return "br"
        if (nl && inY) return "l"
        if (nr && inY) return "r"
        if (nt && inX) return "t"
        if (nb && inX) return "b"
        if (px > x0 && px < x1 && py > y0 && py < y1) return "move"
        return "outside"
    }

    function cursorFor(zone) {
        switch (zone) {
        case "tl": case "br": return Qt.SizeFDiagCursor
        case "tr": case "bl": return Qt.SizeBDiagCursor
        case "l": case "r": return Qt.SizeHorCursor
        case "t": case "b": return Qt.SizeVerCursor
        case "move": return Qt.SizeAllCursor
        default: return Qt.CrossCursor
        }
    }

    // New rect for a drag: s = rect at press, (ux, uy) = pointer, normalized.
    function dragTo(mode, s, ux, uy, ax, ay) {
        const ratio = normRatio
        if (mode === "move") {
            const dx = ux - ax, dy = uy - ay
            return Qt.rect(clamp(s.x + dx, 0, 1 - s.width), clamp(s.y + dy, 0, 1 - s.height), s.width, s.height)
        }
        let L = s.x, T = s.y, R = s.x + s.width, B = s.y + s.height
        ux = clamp(ux, 0, 1)
        uy = clamp(uy, 0, 1)
        if (mode === "new") {
            // from the press point (ax, ay) to the pointer
            let w = Math.max(Math.abs(ux - ax), minW), h = Math.max(Math.abs(uy - ay), minH)
            const sx = ux >= ax ? 1 : -1, sy = uy >= ay ? 1 : -1
            if (ratio > 0) {
                h = w / ratio
                const roomY = sy > 0 ? 1 - ay : ay, roomX = sx > 0 ? 1 - ax : ax
                if (h > roomY) { h = roomY; w = h * ratio }
                if (w > roomX) { w = roomX; h = w / ratio }
            } else {
                w = Math.min(w, sx > 0 ? 1 - ax : ax)
                h = Math.min(h, sy > 0 ? 1 - ay : ay)
            }
            return Qt.rect(sx > 0 ? ax : ax - w, sy > 0 ? ay : ay - h, w, h)
        }
        if (mode.indexOf("l") >= 0) L = clamp(ux, 0, R - minW)
        if (mode.indexOf("r") >= 0) R = clamp(ux, L + minW, 1)
        if (mode.indexOf("t") >= 0) T = clamp(uy, 0, B - minH)
        if (mode.indexOf("b") >= 0) B = clamp(uy, T + minH, 1)
        if (ratio <= 0)
            return Qt.rect(L, T, R - L, B - T)

        let w = R - L, h = B - T
        if (mode === "l" || mode === "r") {          // width leads, height follows, centered
            h = w / ratio
            const cy = s.y + s.height / 2
            if (h > 1) { h = 1; w = h * ratio }
            T = clamp(cy - h / 2, 0, 1 - h)
            if (mode === "l") L = R - w; else R = L + w
            return Qt.rect(L, T, w, h)
        }
        if (mode === "t" || mode === "b") {          // height leads
            w = h * ratio
            const cx = s.x + s.width / 2
            if (w > 1) { w = 1; h = w / ratio }
            L = clamp(cx - w / 2, 0, 1 - w)
            if (mode === "t") T = B - h; else B = T + h
            return Qt.rect(L, T, w, h)
        }
        // corners: keep the opposite corner, follow the larger change
        if (w / h > ratio) h = w / ratio; else w = h * ratio
        const fixedX = mode.indexOf("l") >= 0 ? R : L, fixedY = mode.indexOf("t") >= 0 ? B : T
        const roomX = mode.indexOf("l") >= 0 ? fixedX : 1 - fixedX
        const roomY = mode.indexOf("t") >= 0 ? fixedY : 1 - fixedY
        if (w > roomX) { w = roomX; h = w / ratio }
        if (h > roomY) { h = roomY; w = h * ratio }
        return Qt.rect(mode.indexOf("l") >= 0 ? fixedX - w : fixedX, mode.indexOf("t") >= 0 ? fixedY - h : fixedY, w, h)
    }

    // ---- drawing ----

    Rectangle { color: Style.cropShade; x: ov.sx; y: ov.sy; width: ov.sw; height: Math.max(0, ov.y0 - ov.sy) }
    Rectangle { color: Style.cropShade; x: ov.sx; y: ov.y1; width: ov.sw; height: Math.max(0, ov.sy + ov.sh - ov.y1) }
    Rectangle { color: Style.cropShade; x: ov.sx; y: ov.y0; width: Math.max(0, ov.x0 - ov.sx); height: ov.y1 - ov.y0 }
    Rectangle { color: Style.cropShade; x: ov.x1; y: ov.y0; width: Math.max(0, ov.sx + ov.sw - ov.x1); height: ov.y1 - ov.y0 }

    Item {
        id: box
        x: ov.x0
        y: ov.y0
        width: ov.x1 - ov.x0
        height: ov.y1 - ov.y0

        Rectangle {
            anchors.fill: parent
            color: Style.clear
            border.width: 1.5
            border.color: "white"
        }

        Repeater {  // rule of thirds, while dragging
            model: 4
            Rectangle {
                required property int index
                readonly property bool vertical: index < 2
                x: vertical ? box.width * (index + 1) / 3 : 0
                y: vertical ? 0 : box.height * (index - 1) / 3
                width: vertical ? 1 : box.width
                height: vertical ? box.height : 1
                color: Qt.rgba(1, 1, 1, 0.55)
                opacity: ov.dragging ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Style.d(Style.fadeMs) } }
            }
        }

        Repeater {  // corner handles (L shapes)
            model: 4
            Item {
                required property int index
                id: corner
                readonly property bool atRight: index % 2 === 1
                readonly property bool atBottom: index >= 2
                x: atRight ? box.width : 0
                y: atBottom ? box.height : 0
                Rectangle { x: corner.atRight ? -18 : -3; y: corner.atBottom ? 0 : -3; width: 21; height: 3; radius: 1.5; color: "white" }
                Rectangle { x: corner.atRight ? 0 : -3; y: corner.atBottom ? -18 : -3; width: 3; height: 21; radius: 1.5; color: "white" }
            }
        }

        Repeater {  // edge handles
            model: 4
            Rectangle {
                required property int index
                readonly property bool vertical: index < 2  // left / right edge
                width: vertical ? 3 : 22
                height: vertical ? 22 : 3
                radius: 1.5
                color: "white"
                visible: (vertical ? box.height : box.width) > 60
                x: vertical ? (index === 0 ? -1.5 : box.width - 1.5) : (box.width - width) / 2
                y: vertical ? (box.height - height) / 2 : (index === 2 ? -1.5 : box.height - 1.5)
            }
        }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton
        property string mode: ""
        property rect start
        property real ax: 0
        property real ay: 0
        cursorShape: ov.vp.spaceHeld ? Qt.OpenHandCursor : ov.cursorFor(ov.dragging ? mode : ov.zoneAt(mouseX, mouseY))

        onPressed: (m) => {
            if (ov.vp.spaceHeld) { m.accepted = false; return }
            const ux = (m.x - ov.sx) / ov.sw, uy = (m.y - ov.sy) / ov.sh
            mode = ov.zoneAt(m.x, m.y)
            if (mode === "outside") {
                if (ux < 0 || ux > 1 || uy < 0 || uy > 1) { m.accepted = false; return }
                mode = "new"
            }
            start = ov.r
            ax = ov.clamp(ux, 0, 1)
            ay = ov.clamp(uy, 0, 1)
            ov.dragRect = start
            ov.dragging = true
        }
        onPositionChanged: (m) => {
            if (!pressed || !ov.dragging) return
            ov.dragRect = ov.dragTo(mode, start, (m.x - ov.sx) / ov.sw, (m.y - ov.sy) / ov.sh, ax, ay)
        }
        onReleased: {
            if (!ov.dragging) return
            const done = ov.dragRect
            if (mode !== "new" || done.width > ov.minW * 1.5 || done.height > ov.minH * 1.5)
                editor.setCrop(done.x, done.y, done.width, done.height)
            ov.dragging = false
        }
        onCanceled: ov.dragging = false
    }
}
