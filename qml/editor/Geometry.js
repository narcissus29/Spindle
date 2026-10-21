.pragma library
// Mark geometry shared by the canvas components. Must match
// app/editor/marks.py (the saved file is drawn from that).

function arrowHead(p1, p2, w) {
    const dx = p2[0] - p1[0], dy = p2[1] - p1[1]
    const len = Math.max(Math.hypot(dx, dy), 1e-6)
    const ux = dx / len, uy = dy / len
    const head = Math.min(Math.max(w * 4.5, 8 * Math.sqrt(w)), len * 0.6)
    const half = head * 0.55
    const bx = p2[0] - ux * head, by = p2[1] - uy * head
    return { tip: [p2[0], p2[1]], left: [bx - uy * half, by + ux * half],
             right: [bx + uy * half, by - ux * half], base: [bx, by] }
}

// [x0, y0, x1, y1] around what a mark paints
function bounds(m) {
    if (!m) return [0, 0, 0, 0]
    if (m.type === "pen" || m.type === "highlight") {
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
        for (const p of m.points) {
            x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]); x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1])
        }
        const pad = m.width / 2
        return [x0 - pad, y0 - pad, x1 + pad, y1 + pad]
    }
    if (m.type === "arrow") {
        const h = arrowHead(m.p1, m.p2, m.width)
        const xs = [m.p1[0], h.tip[0], h.left[0], h.right[0]], ys = [m.p1[1], h.tip[1], h.left[1], h.right[1]]
        const pad = m.width / 2
        return [Math.min(...xs) - pad, Math.min(...ys) - pad, Math.max(...xs) + pad, Math.max(...ys) + pad]
    }
    const r = m.rect
    return [r[0], r[1], r[0] + r[2], r[1] + r[3]]
}

function toPoints(list) {
    return list.map(p => Qt.point(p[0], p[1]))
}

function rectBetween(a, b) {
    return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1])]
}
