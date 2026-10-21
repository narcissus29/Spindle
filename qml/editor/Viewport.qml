import QtQuick
import QtQuick.Effects
import QtQuick.Window
import "."

// The canvas: the page or photo, zoomed and panned, with the crop overlay.
//
// Geometry (all sizes in logical px = content units * k):
//   card   the part of the page on screen (the crop, or the whole page while
//          cropping), centered + pan. Turns are animated on the card: when
//          the picture turns right, the new state is applied at once and the
//          card starts a quarter turn back, then eases to 0.
//   stage  the whole displayed page (after the user's rotation)
//   rotor  the page before the user's rotation, rotated by editor.rot
//
// Entering Crop animates `reveal` 0 -> 1: the clipped card opens up to the
// whole page and the shading fades in; leaving closes it again.
Item {
    id: vp

    required property QtObject live  // color values while a slider is dragged
    property bool spaceHeld: false
    property string aspect: "free"   // crop preset: free | original | 1:1 | 4:3 | 16:9 | exact
    property bool portrait: false
    // An exact output size in the edit state (also after undo / redo)
    // shows as the "Exact size" preset; clearing it goes back to Free.
    Connections {
        target: editor
        function onChanged() {
            if (editor.outputWidth > 0 && vp.aspect !== "exact") vp.aspect = "exact"
            else if (editor.outputWidth === 0 && vp.aspect === "exact") vp.aspect = "free"
        }
    }

    readonly property bool cropping: editor.tool === "crop"
    readonly property bool sideways: editor.rot % 180 !== 0
    readonly property real baseW: Math.max(1, editor.pageWidth)
    readonly property real baseH: Math.max(1, editor.pageHeight)
    readonly property real stageW: sideways ? baseH : baseW
    readonly property real stageH: sideways ? baseW : baseH

    property real reveal: cropping || !editor.hasCrop ? 1 : 0
    Behavior on reveal { NumberAnimation { duration: Style.d(Style.revealMs); easing.type: Easing.InOutCubic } }
    readonly property rect crop: editor.crop
    readonly property real rx: crop.x * (1 - reveal)
    readonly property real ry: crop.y * (1 - reveal)
    readonly property real rw: crop.width + (1 - crop.width) * reveal
    readonly property real rh: crop.height + (1 - crop.height) * reveal

    readonly property real margin: 40
    readonly property real fitScale: Math.max(1e-4, Math.min((width - 2 * margin) / (rw * stageW),
                                                            (height - 2 * margin) / (rh * stageH)))
    property real zoom: 1    // times the fit
    property real panX: 0
    property real panY: 0
    property bool turning: false
    readonly property real kTarget: fitScale * zoom
    property real k: kTarget  // logical px per content unit (eased during turns)
    Behavior on k {
        enabled: vp.turning
        NumberAnimation { duration: Style.d(Style.turnMs); easing.type: Easing.OutCubic }
    }

    readonly property real dpr: Screen.devicePixelRatio
    // 100% = one image pixel per screen pixel (images), 96 DPI (PDFs)
    readonly property real unitAt100: editor.isPdf ? 96 / 72 : 1 / dpr
    readonly property real percent: k / unitAt100 * 100
    readonly property bool pannable: card.width > width + 1 || card.height > height + 1

    // where the whole page sits, for the crop overlay
    readonly property real stageX: card.x + stage.x
    readonly property real stageY: card.y + stage.y
    readonly property real stagePxW: stage.width
    readonly property real stagePxH: stage.height
    readonly property alias overlay: cropOverlay
    readonly property alias marksLayer: marksLayer
    readonly property alias cardItem: card  // the part of the page on screen

    readonly property bool adjusting: Math.abs(live.brightness) > 1e-4 || Math.abs(live.contrast) > 1e-4
                                      || Math.abs(live.saturation) > 1e-4

    // ---- zoom / pan ----

    function clampZoom(z) {
        const most = Math.max(1, 16 * unitAt100 / fitScale)  // up to 1600%
        return Math.max(0.25, Math.min(z, most))
    }
    function panLimit(z) {
        const w = rw * stageW * fitScale * z, h = rh * stageH * fitScale * z
        return Qt.point(w > width ? (w - width) / 2 + margin : 0, h > height ? (h - height) / 2 + margin : 0)
    }
    function clampPan() {
        const lim = panLimit(zoom)
        panX = Math.max(-lim.x, Math.min(lim.x, panX))
        panY = Math.max(-lim.y, Math.min(lim.y, panY))
    }
    function zoomAt(z, px, py) {
        z = clampZoom(z)
        const f = z / zoom
        panX = (px - width / 2) - (px - width / 2 - panX) * f
        panY = (py - height / 2) - (py - height / 2 - panY) * f
        zoom = z
        clampPan()
    }
    function animateZoom(z, px, py) {
        z = clampZoom(z)
        const fromZ = zoomGoal
        const fromX = zoomAnim.running ? zoomAnim.px : panX
        const fromY = zoomAnim.running ? zoomAnim.py : panY
        const f = z / fromZ
        const lim = panLimit(z)
        zoomAnim.z = z
        zoomAnim.px = Math.max(-lim.x, Math.min(lim.x, (px - width / 2) - (px - width / 2 - fromX) * f))
        zoomAnim.py = Math.max(-lim.y, Math.min(lim.y, (py - height / 2) - (py - height / 2 - fromY) * f))
        zoomAnim.restart()
    }
    // Repeated clicks step from where the running animation is heading.
    readonly property real zoomGoal: zoomAnim.running ? zoomAnim.z : zoom
    function zoomIn() { animateZoom(zoomGoal * 1.25, width / 2, height / 2) }
    function zoomOut() { animateZoom(zoomGoal / 1.25, width / 2, height / 2) }
    function actualSize() { animateZoom(unitAt100 / fitScale, width / 2, height / 2) }
    function fit() {
        zoomAnim.z = 1
        zoomAnim.px = 0
        zoomAnim.py = 0
        zoomAnim.restart()
    }

    ParallelAnimation {
        id: zoomAnim
        property real z: 1
        property real px: 0
        property real py: 0
        NumberAnimation { target: vp; property: "zoom"; to: zoomAnim.z; duration: Style.d(220); easing.type: Easing.OutCubic }
        NumberAnimation { target: vp; property: "panX"; to: zoomAnim.px; duration: Style.d(220); easing.type: Easing.OutCubic }
        NumberAnimation { target: vp; property: "panY"; to: zoomAnim.py; duration: Style.d(220); easing.type: Easing.OutCubic }
    }

    property string tool: editor.tool
    onToolChanged: fit()
    property int page: editor.page
    onPageChanged: {
        zoomAnim.stop()
        zoom = 1
        panX = 0
        panY = 0
        settle.stop()
        renderWidth = wantWidth
    }

    // ---- turning (rotate / flip, also on undo / redo) ----

    Connections {
        target: editor
        function onTurned(op) {
            turnAnim.stop()
            vp.turning = true
            card.spin = op === "cw" ? -90 : op === "ccw" ? 90 : 0
            card.flipX = op === "h" ? -1 : 1
            card.flipY = op === "v" ? -1 : 1
            vp.panX = 0
            vp.panY = 0
            turnAnim.start()
        }
    }

    ParallelAnimation {
        id: turnAnim
        NumberAnimation { target: card; property: "spin"; to: 0; duration: Style.d(Style.turnMs); easing.type: Easing.OutCubic }
        NumberAnimation { target: card; property: "flipX"; to: 1; duration: Style.d(Style.turnMs); easing.type: Easing.InOutCubic }
        NumberAnimation { target: card; property: "flipY"; to: 1; duration: Style.d(Style.turnMs); easing.type: Easing.InOutCubic }
        onFinished: vp.turning = false
    }

    // ---- how sharp to render (PDF pages, software-renderer previews) ----

    readonly property int wantWidth: Math.max(256, Math.min(8192, Math.ceil(baseW * k * dpr / 128) * 128))
    property int renderWidth: 0
    onWantWidthChanged: {
        if (renderWidth === 0)
            renderWidth = wantWidth
        else if (wantWidth > renderWidth * 1.05 || wantWidth < renderWidth * 0.6)
            settle.restart()
    }
    Timer {  // one-shot after zooming stops
        id: settle
        interval: 140
        onTriggered: vp.renderWidth = vp.wantWidth
    }

    readonly property string imageSource: {
        if (editor.isPdf)
            return "image://doc/page/" + editor.page + "/" + renderWidth
        const w = Math.min(renderWidth, editor.previewWidth)
        if (adjusting)
            return "image://doc/adjusted/" + w + "/" + live.brightness.toFixed(3) + "/"
                   + live.contrast.toFixed(3) + "/" + live.saturation.toFixed(3)
        return "image://doc/page/0/" + w
    }

    // ---- input ----

    MouseArea {
        id: panArea
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton
        property bool panning: false
        property real lastX: 0
        property real lastY: 0
        cursorShape: panning ? Qt.ClosedHandCursor
                     : (vp.pannable && (!vp.cropping || vp.spaceHeld)) ? Qt.OpenHandCursor : Qt.ArrowCursor
        onPressed: (m) => {
            if (m.button === Qt.MiddleButton || vp.spaceHeld || (!vp.cropping && vp.pannable)) {
                panning = true
                lastX = m.x
                lastY = m.y
                zoomAnim.stop()
            } else {
                m.accepted = false
            }
        }
        onPositionChanged: (m) => {
            if (!panning) return
            vp.panX += m.x - lastX
            vp.panY += m.y - lastY
            lastX = m.x
            lastY = m.y
            vp.clampPan()
        }
        onReleased: panning = false
        onCanceled: panning = false
        onWheel: (w) => {
            const ctrl = (w.modifiers & Qt.ControlModifier) !== 0
            if (!ctrl && (w.pixelDelta.x !== 0 || w.pixelDelta.y !== 0)) {  // touchpad: scroll pans
                vp.panX += w.pixelDelta.x
                vp.panY += w.pixelDelta.y
                vp.clampPan()
                return
            }
            const steps = w.angleDelta.y / 120
            if (steps !== 0) {
                zoomAnim.stop()
                vp.zoomAt(vp.zoom * Math.pow(1.2, steps), w.x, w.y)
            }
        }
    }

    PinchHandler {  // touchpad / touchscreen pinch
        target: null
        property real startZoom: 1
        onActiveChanged: if (active) { zoomAnim.stop(); startZoom = vp.zoom }
        onActiveScaleChanged: if (active) vp.zoomAt(startZoom * activeScale, centroid.position.x, centroid.position.y)
    }

    // ---- the page ----

    Item {
        id: card
        property real spin: 0
        property real flipX: 1
        property real flipY: 1
        width: vp.rw * vp.stageW * vp.k
        height: vp.rh * vp.stageH * vp.k
        x: Math.round((vp.width - width) / 2 + vp.panX)
        y: Math.round((vp.height - height) / 2 + vp.panY)
        transform: [
            Scale { origin.x: card.width / 2; origin.y: card.height / 2; xScale: card.flipX; yScale: card.flipY },
            Rotation { origin.x: card.width / 2; origin.y: card.height / 2; angle: card.spin }
        ]

        Rectangle {  // soft shadow + edge
            anchors.fill: parent
            anchors.topMargin: 2
            anchors.bottomMargin: -3
            radius: 3
            color: Style.cardShadow
        }
        Rectangle {
            anchors.fill: parent
            anchors.margins: -1
            color: Style.clear
            border.width: 1
            border.color: Style.canvasEdge
        }

        Item {
            id: frame
            anchors.fill: parent
            clip: vp.reveal < 0.999

            Item {
                id: stage
                x: -vp.rx * width
                y: -vp.ry * height
                width: vp.stageW * vp.k
                height: vp.stageH * vp.k

                Item {
                    id: rotor
                    anchors.centerIn: parent
                    width: vp.baseW * vp.k
                    height: vp.baseH * vp.k
                    rotation: editor.rot

                    Item {
                        id: mirrorBox
                        anchors.fill: parent
                        transform: Scale { origin.x: mirrorBox.width / 2; xScale: editor.mirror ? -1 : 1 }

                        Image {  // checkerboard behind transparent images
                            anchors.fill: parent
                            visible: editor.hasAlpha
                            source: editor.hasAlpha ? "image://doc/checker" : ""
                            fillMode: Image.Tile
                            smooth: false
                        }

                        // Photo on the GPU: the preview as a texture; color
                        // changes previewed by MultiEffect (same math as saving).
                        Image {
                            id: photo
                            anchors.fill: parent
                            visible: !editor.isPdf && !editor.software && !vp.adjusting
                            source: !editor.isPdf && !editor.software ? "image://doc/page/0/" + editor.previewWidth : ""
                            asynchronous: true
                            smooth: true
                            mipmap: true
                            opacity: status === Image.Ready ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: Style.d(160); easing.type: Easing.OutCubic } }
                        }
                        MultiEffect {
                            anchors.fill: parent
                            source: photo
                            visible: !editor.isPdf && !editor.software && vp.adjusting
                            autoPaddingEnabled: false
                            brightness: vp.live.brightness
                            contrast: vp.live.contrast
                            saturation: vp.live.saturation
                        }

                        // PDF pages, and photos on the software renderer.
                        SwapImage {
                            anchors.fill: parent
                            visible: editor.isPdf || editor.software
                            source: editor.isPdf || editor.software ? vp.imageSource : ""
                        }

                        // Annotations, redaction boxes, search matches.
                        MarksLayer {
                            id: marksLayer
                            width: vp.baseW
                            height: vp.baseH
                            k: vp.k
                            mirrored: editor.mirror
                        }
                    }
                }
            }

            Rectangle {  // deleted page: washed out, with a way back
                anchors.fill: parent
                visible: opacity > 0
                opacity: editor.pageDeleted ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Style.d(Style.fadeMs) } }
                color: Qt.rgba(Style.windowBg.r, Style.windowBg.g, Style.windowBg.b, 0.78)

                Column {
                    anchors.centerIn: parent
                    spacing: 12
                    Icon { anchors.horizontalCenter: parent.horizontalCenter; name: "trash"; size: 32; color: Style.inkSoft }
                    Text {
                        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "This page will be left out"
                        color: Style.inkSoft
                        font.pixelSize: Style.textSize
                    }
                    PillButton {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Restore page"
                        icon: "restore"
                        onClicked: editor.restorePage()
                    }
                }
            }
        }
    }

    CropOverlay {
        id: cropOverlay
        anchors.fill: parent
        vp: vp
    }

    MarkInput {
        vp: vp
        ink: marksLayer
    }
}
