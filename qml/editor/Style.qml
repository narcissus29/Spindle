pragma Singleton
import QtQuick
import ".." as Wheel

// The editor's look: the wheel's Theme (same palettes, same timings) plus
// the surfaces a window needs. Picked by the same `theme` config key.
Wheel.Theme {
    name: editor.themeName
    reduced: editor.reduceAnimations

    readonly property bool warm: name === "orange"

    // ---- surfaces ----
    readonly property color windowBg: warm ? "#fbf3ec" : "#edf2fa"
    readonly property color canvasBg: warm ? "#f1e3d7" : "#dde6f2"
    readonly property color canvasEdge: warm ? "#e7d2c1" : "#cfdbeb"
    readonly property color panel: warm ? "#fffaf6" : "#ffffff"
    readonly property color panelBorder: warm ? "#efdccd" : "#d8e3f2"
    readonly property color field: warm ? "#fdf5ef" : "#f4f7fc"
    readonly property color divider: warm ? "#f1e2d6" : "#e4ebf5"
    readonly property color cardShadow: warm ? Qt.rgba(0.35, 0.13, 0.04, 0.08) : Qt.rgba(0.07, 0.15, 0.30, 0.08)
    readonly property color clear: "transparent"

    // ---- text ----
    readonly property color inkSoft: warm ? "#9a6a4c" : "#5b7394"
    readonly property color inkFaint: warm ? "#c9a993" : "#9db0c9"

    // ---- accent (the wheel's hover blue / orange) ----
    readonly property color accent: hotOuter
    readonly property color accentTop: hotInner
    readonly property color accentSoft: warm ? Qt.rgba(0.94, 0.27, 0.13, 0.10) : Qt.rgba(0.12, 0.36, 0.85, 0.10)
    readonly property color accentLine: warm ? Qt.rgba(0.94, 0.27, 0.13, 0.35) : Qt.rgba(0.12, 0.36, 0.85, 0.35)
    readonly property color hover: warm ? Qt.rgba(0.42, 0.20, 0.09, 0.06) : Qt.rgba(0.12, 0.23, 0.37, 0.06)
    readonly property color track: warm ? "#efdfd2" : "#dbe4f1"
    readonly property color danger: cancelInk
    readonly property color dangerSoft: Qt.rgba(0.70, 0.15, 0.12, 0.08)

    // ---- overlays ----
    readonly property color scrim: Qt.rgba(0.05, 0.10, 0.19, 0.30)
    readonly property color cropShade: Qt.rgba(0.04, 0.08, 0.15, 0.55)
    readonly property color tipBg: Qt.rgba(0.08, 0.14, 0.24, 0.92)

    // ---- sizes ----
    readonly property int radius: 14
    readonly property int radiusSmall: 9
    readonly property int textSize: 13
    readonly property int smallSize: 12
    readonly property int titleSize: 15

    // ---- timings (ms) ----
    readonly property int panelMs: 220
    readonly property int turnMs: 300
    readonly property int revealMs: 320
}
