import QtQuick

// Colors, sizes and timings in one place. One instance is created in
// Main.qml and handed to every component as `theme`.
//
// Two palettes, picked by `name` ("blue" | "orange", from config). `name` is
// set once at startup, so each color binding is evaluated once and never
// again: switching palettes has no per-frame cost.
QtObject {
    // Set from config (reduce_animations). Durations collapse to 0.
    property bool reduced: false
    function d(ms) { return reduced ? 0 : Math.round(ms) }

    // Set from config (theme).
    property string name: "blue"

    // ---- timing (ms) ----
    readonly property int openMs: 180
    readonly property int closeMs: 120
    readonly property int hoverMs: 170
    readonly property int fadeMs: 140
    readonly property int exitMs: 90
    readonly property int switchMs: 260
    readonly property int staggerMs: 20
    readonly property real swingDeg: 16
    readonly property real hoverScale: 1.04

    // ---- palettes ----

    // macOS selection blue: icy blue-white glass, blue hover, navy ink.
    readonly property QtObject bluePalette: QtObject {
        // glass wedges (#EAF2FF ~75% at the hub, slightly cooler at the rim)
        readonly property color glassInner: Qt.rgba(0.918, 0.949, 1.000, 0.75)
        readonly property color glassOuter: Qt.rgba(0.855, 0.906, 0.988, 0.78)
        readonly property color sheen: Qt.rgba(0.965, 0.980, 1.000, 0.40)
        readonly property color sheenClear: Qt.rgba(0.965, 0.980, 1.000, 0.0)
        readonly property color edge: Qt.rgba(0.749, 0.831, 0.961, 0.80)       // #BFD4F5
        readonly property color rim: Qt.rgba(0.749, 0.831, 0.961, 1.00)        // #BFD4F5
        readonly property color shadow: Qt.rgba(0.07, 0.15, 0.30, 0.22)
        readonly property color shadowClear: Qt.rgba(0.07, 0.15, 0.30, 0.0)
        // hovered wedge
        readonly property color hotInner: "#4c8dff"
        readonly property color hotOuter: "#1e5bd8"
        readonly property color hotEdge: Qt.rgba(0.86, 0.92, 1.00, 0.65)
        readonly property color hotSheen: Qt.rgba(1, 1, 1, 0.30)
        readonly property color glow: Qt.rgba(0.30, 0.55, 1.00, 0.28)
        // center hub + pill
        readonly property color hubInner: Qt.rgba(0.975, 0.985, 1.000, 0.80)
        readonly property color hubOuter: Qt.rgba(0.890, 0.930, 0.995, 0.80)
        readonly property color pillTop: Qt.rgba(0.995, 0.997, 1.000, 0.97)
        readonly property color pillBottom: Qt.rgba(0.935, 0.957, 0.995, 0.95)
        readonly property color pillBorder: Qt.rgba(1, 1, 1, 0.95)
        readonly property color cancelTop: Qt.rgba(1.000, 0.955, 0.955, 0.97)
        readonly property color cancelBottom: Qt.rgba(1.000, 0.870, 0.870, 0.95)
        readonly property color cancelBorder: Qt.rgba(0.95, 0.55, 0.55, 0.90)
        readonly property color cancelInk: "#b3261e"
        readonly property color warnTop: Qt.rgba(1.000, 0.975, 0.910, 0.97)
        readonly property color warnBottom: Qt.rgba(1.000, 0.925, 0.760, 0.95)
        readonly property color warnBorder: Qt.rgba(0.93, 0.66, 0.20, 0.90)
        readonly property color warnInk: "#8a4b00"
        // text + icons
        readonly property color ink: "#1e3a5f"
        readonly property color inkHot: "#ffffff"
    }

    // Warm peach glass with a red-orange hover (the original look).
    readonly property QtObject orangePalette: QtObject {
        readonly property color glassInner: Qt.rgba(1.00, 0.955, 0.915, 0.80)
        readonly property color glassOuter: Qt.rgba(1.00, 0.790, 0.640, 0.82)
        readonly property color sheen: Qt.rgba(1, 1, 1, 0.42)
        readonly property color sheenClear: Qt.rgba(1, 1, 1, 0.0)
        readonly property color edge: Qt.rgba(1, 1, 1, 0.55)
        readonly property color rim: Qt.rgba(1, 1, 1, 0.85)
        readonly property color shadow: Qt.rgba(0.35, 0.13, 0.04, 0.22)
        readonly property color shadowClear: Qt.rgba(0.35, 0.13, 0.04, 0.0)
        readonly property color hotInner: "#ff9858"
        readonly property color hotOuter: "#ef4420"
        readonly property color hotEdge: Qt.rgba(1, 0.92, 0.85, 0.65)
        readonly property color hotSheen: Qt.rgba(1, 1, 1, 0.30)
        readonly property color glow: Qt.rgba(1.0, 0.36, 0.14, 0.28)
        readonly property color hubInner: Qt.rgba(1.00, 0.975, 0.950, 0.78)
        readonly property color hubOuter: Qt.rgba(1.00, 0.860, 0.760, 0.80)
        readonly property color pillTop: Qt.rgba(1.00, 0.990, 0.975, 0.97)
        readonly property color pillBottom: Qt.rgba(1.00, 0.900, 0.825, 0.95)
        readonly property color pillBorder: Qt.rgba(1, 1, 1, 0.95)
        readonly property color cancelTop: Qt.rgba(1.000, 0.955, 0.955, 0.97)
        readonly property color cancelBottom: Qt.rgba(1.000, 0.870, 0.870, 0.95)
        readonly property color cancelBorder: Qt.rgba(0.95, 0.55, 0.55, 0.90)
        readonly property color cancelInk: "#b3261e"
        readonly property color warnTop: Qt.rgba(1.000, 0.975, 0.910, 0.97)
        readonly property color warnBottom: Qt.rgba(1.000, 0.925, 0.760, 0.95)
        readonly property color warnBorder: Qt.rgba(0.93, 0.66, 0.20, 0.90)
        readonly property color warnInk: "#8a4b00"
        readonly property color ink: "#6a3416"
        readonly property color inkHot: "#ffffff"
    }

    readonly property QtObject palette: name === "orange" ? orangePalette : bluePalette

    // ---- active colors (what components read) ----

    // glass wedges
    readonly property color glassInner: palette.glassInner
    readonly property color glassOuter: palette.glassOuter
    readonly property color sheen: palette.sheen
    readonly property color sheenClear: palette.sheenClear
    readonly property color edge: palette.edge
    readonly property color rim: palette.rim
    readonly property color shadow: palette.shadow
    readonly property color shadowClear: palette.shadowClear

    // hovered wedge
    readonly property color hotInner: palette.hotInner
    readonly property color hotOuter: palette.hotOuter
    readonly property color hotEdge: palette.hotEdge
    readonly property color hotSheen: palette.hotSheen
    readonly property color glow: palette.glow

    // center hub + pill
    readonly property color hubInner: palette.hubInner
    readonly property color hubOuter: palette.hubOuter
    readonly property color pillTop: palette.pillTop
    readonly property color pillBottom: palette.pillBottom
    readonly property color pillBorder: palette.pillBorder
    readonly property color cancelTop: palette.cancelTop
    readonly property color cancelBottom: palette.cancelBottom
    readonly property color cancelBorder: palette.cancelBorder
    readonly property color cancelInk: palette.cancelInk
    readonly property color warnTop: palette.warnTop
    readonly property color warnBottom: palette.warnBottom
    readonly property color warnBorder: palette.warnBorder
    readonly property color warnInk: palette.warnInk

    // text
    readonly property color ink: palette.ink
    readonly property color inkHot: palette.inkHot
}
