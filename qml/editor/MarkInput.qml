import QtQuick
import "."
import "Geometry.js" as Geo

// Pointer input for Annotate and Redact. Points are turned into content
// units through the marks layer itself (which knows the zoom, the page's
// rotation and mirror). A stroke / shape / box lives in the layer while
// the button is down and goes to the bridge once, on release.
MouseArea {
    id: input

    required property Item vp
    required property Item ink  // the MarksLayer

    readonly property bool redacting: editor.tool === "redact"
    readonly property string tool: redacting ? "redact" : editor.annotateTool
    property string mode: ""   // draw | move | box
    property var start: [0, 0]
    property var pts: []
    property int hoverId: -1

    anchors.fill: parent
    enabled: (editor.tool === "annotate" || redacting) && !vp.turning && !editor.pageDeleted
    hoverEnabled: true
    preventStealing: true
    acceptedButtons: Qt.LeftButton
    cursorShape: vp.spaceHeld ? Qt.OpenHandCursor
                 : mode === "move" ? Qt.ClosedHandCursor
                 : tool === "select" ? (hoverId >= 0 ? Qt.OpenHandCursor : Qt.ArrowCursor)
                 : tool === "text" ? Qt.IBeamCursor : Qt.CrossCursor

    function at(mx, my) {
        const p = ink.mapFromItem(input, mx, my)
        return [p.x, p.y]
    }
    function units(screenPx) { return screenPx / vp.k }
    function presetWidth() {
        const presets = editor.widthPresets[tool === "select" ? "pen" : tool]
        return units(presets[editor.widthIndex])
    }
    function liveStroke() {
        return { type: tool, color: editor.markColor, width: presetWidth(), points: pts }
    }

    // ---- the visible part of the page, in content units ----
    // The page itself, or the crop when one is set: marks start inside it,
    // shapes and text stay inside it, freehand strokes are clipped to it.
    property var area: [0, 0, 1, 1]
    function visibleArea() {
        const card = vp.cardItem
        const a = ink.mapFromItem(card, 0, 0), b = ink.mapFromItem(card, card.width, card.height)
        return [Math.max(0, Math.min(a.x, b.x)), Math.max(0, Math.min(a.y, b.y)),
                Math.min(vp.baseW, Math.max(a.x, b.x)), Math.min(vp.baseH, Math.max(a.y, b.y))]
    }
    function inside(p) { return p[0] >= area[0] && p[0] <= area[2] && p[1] >= area[1] && p[1] <= area[3] }
    function clampPoint(p) {
        return [Math.max(area[0], Math.min(area[2], p[0])), Math.max(area[1], Math.min(area[3], p[1]))]
    }
    // How far a mark may move and still be inside, per axis.
    function clampMove(id, dx, dy) {
        const m = editor.marks.find(mk => mk.id === id)
        if (!m || m.type === "pen" || m.type === "highlight") return [dx, dy]
        const b = Geo.bounds(m)
        const lo = [area[0] - b[0], area[1] - b[1]], hi = [area[2] - b[2], area[3] - b[3]]
        return [lo[0] > hi[0] ? 0 : Math.max(lo[0], Math.min(hi[0], dx)),
                lo[1] > hi[1] ? 0 : Math.max(lo[1], Math.min(hi[1], dy))]
    }

    onPressed: (m) => {
        if (vp.spaceHeld) { m.accepted = false; return }
        if (ink.editing) ink.commitText()  // a click elsewhere ends typing
        area = visibleArea()
        const p = at(m.x, m.y)
        start = p
        mode = ""
        if (!inside(p) && tool !== "select") return  // nothing starts off the page
        if (redacting) {
            const id = editor.redactionAt(p[0], p[1])
            ink.selectedBox = id
            if (id < 0) {
                mode = "box"
                ink.live = { type: "redact", rect: [p[0], p[1], 0, 0] }
            }
            return
        }
        if (tool === "select") {
            const id = editor.markAt(p[0], p[1], units(6))
            editor.selectMark(id)
            if (id >= 0) {
                mode = "move"
                ink.moveId = id
                ink.moveDx = 0
                ink.moveDy = 0
            }
        } else if (tool === "text") {
            const id = editor.markAt(p[0], p[1], 0)
            const hitMark = editor.marks.find(mk => mk.id === id)
            if (hitMark && hitMark.type === "text")
                ink.startText(hitMark.rect[0], hitMark.rect[1], hitMark.size, hitMark.color, hitMark.text, hitMark.id, area)
            else
                ink.startText(p[0], p[1] - units(editor.widthPresets.text[editor.widthIndex]) * 0.6,
                              units(editor.widthPresets.text[editor.widthIndex]), editor.markColor, "", -1, area)
        } else if (tool === "pen" || tool === "highlight") {
            mode = "draw"
            pts = [p]
            ink.live = liveStroke()
        } else if (tool === "arrow") {
            mode = "draw"
            ink.live = { type: "arrow", color: editor.markColor, width: presetWidth(), p1: p, p2: p }
        } else if (tool === "rect") {
            mode = "draw"
            ink.live = { type: "rect", color: editor.markColor, width: presetWidth(), rect: [p[0], p[1], 0, 0] }
        }
    }

    onPositionChanged: (m) => {
        const p = at(m.x, m.y)
        if (!pressed) {
            hoverId = tool === "select" ? editor.markAt(p[0], p[1], units(6)) : -1
            return
        }
        if (mode === "move") {
            const d = clampMove(ink.moveId, p[0] - start[0], p[1] - start[1])
            ink.moveDx = d[0]
            ink.moveDy = d[1]
        } else if (mode === "box") {
            ink.live = { type: "redact", rect: Geo.rectBetween(start, clampPoint(p)) }
        } else if (mode === "draw") {
            if (tool === "pen" || tool === "highlight") {
                const last = pts[pts.length - 1]
                if (Math.hypot(p[0] - last[0], p[1] - last[1]) < units(1.5)) return
                pts = pts.concat([p])
                ink.live = liveStroke()
            } else if (tool === "arrow") {
                ink.live = Object.assign({}, ink.live, { p2: clampPoint(p) })
            } else if (tool === "rect") {
                ink.live = Object.assign({}, ink.live, { rect: Geo.rectBetween(start, clampPoint(p)) })
            }
        }
    }

    function finish() {
        const live = ink.live
        if (mode === "move" && (ink.moveDx !== 0 || ink.moveDy !== 0))
            editor.moveMark(ink.moveId, ink.moveDx, ink.moveDy)
        else if (mode === "box" && live && live.rect[2] > units(4) && live.rect[3] > units(4))
            editor.addRedaction(live.rect[0], live.rect[1], live.rect[2], live.rect[3])
        else if (mode === "draw" && live) {
            const big = live.type === "arrow" ? Math.hypot(live.p2[0] - live.p1[0], live.p2[1] - live.p1[1]) > units(6)
                      : live.type === "rect" ? live.rect[2] > units(4) && live.rect[3] > units(4) : true
            if (big)
                editor.addMark(live)
        }
        ink.live = null
        ink.moveId = -1
        ink.moveDx = 0
        ink.moveDy = 0
        mode = ""
        pts = []
    }
    onReleased: finish()
    onCanceled: finish()

    onDoubleClicked: (m) => {
        if (redacting || tool !== "select") return
        const p = at(m.x, m.y)
        const hitMark = editor.marks.find(mk => mk.id === editor.markAt(p[0], p[1], units(6)))
        if (hitMark && hitMark.type === "text")
            ink.startText(hitMark.rect[0], hitMark.rect[1], hitMark.size, hitMark.color, hitMark.text, hitMark.id,
                          visibleArea())
    }
}
