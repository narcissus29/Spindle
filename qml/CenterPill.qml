import QtQuick
import QtQuick.Shapes

// Center hub: glass disc, a rounded pill whose text crossfades when it
// changes, and (while files are parked) a thumbnail or document icon of the
// first file above the pill, stacked with a count badge for a batch.
// A PDF shows its document icon first and crossfades to the real first page
// when the helper has rendered it. `danger` tints the pill red ("Cancel"),
// `warn` amber (a miss: "Smallest: 340 KB"). `entry` turns the pill into
// a size field ("75" + a KB / MB switch) for Compress > Custom. A small ×
// on the stack's top-left corner puts the parked files away (clearClicked).
Item {
    id: pill

    required property QtObject theme
    property real hubR: 60
    property string text: ""
    property bool parked: false
    property string thumbSource: ""   // file:// URL of the first parked image, else ""
    property string firstLabel: ""    // format of the first file ("PDF")
    property int count: 0             // number of files
    property bool danger: false       // hovering "Cancel" while busy
    property bool warn: false         // the result is a miss
    property bool entry: false        // asking for a custom size
    property string lastSize: ""      // "75 KB": prefilled
    property string entryError: ""
    property bool canClear: false     // show the × on the stack
    signal entryAccepted(string text)
    signal entryCanceled()
    signal clearClicked()

    property string unit: "KB"
    onEntryChanged: {
        if (!entry) {
            entryError = ""
            return
        }
        const m = /^([\d.]+)\s*(KB|MB)$/.exec(lastSize)
        sizeField.text = m ? m[1] : ""
        unit = m ? m[2] : "KB"
        sizeField.forceActiveFocus()
        sizeField.selectAll()
    }
    function submit() {
        if (sizeField.text.trim() !== "")
            entryAccepted(sizeField.text.trim() + " " + unit)
    }
    readonly property color topColor: danger ? theme.cancelTop : warn ? theme.warnTop : theme.pillTop
    readonly property color bottomColor: danger ? theme.cancelBottom : warn ? theme.warnBottom : theme.pillBottom
    readonly property color inkColor: danger ? theme.cancelInk : warn ? theme.warnInk : theme.ink

    width: hubR * 2
    height: hubR * 2

    // What the thumbnail shows. Held until it has faded out, so a file
    // being replaced doesn't flicker to the next one mid-fade.
    property string heldSource: ""
    property string heldLabel: ""
    property int heldCount: 0
    // (parked / thumbSource / firstLabel / count change on the same bridge
    // signal, in no fixed order, so each one refreshes the held values.)
    function hold() {
        if (parked) {
            heldSource = thumbSource
            heldLabel = firstLabel
            heldCount = count
        }
    }
    onParkedChanged: hold()
    onThumbSourceChanged: hold()
    onFirstLabelChanged: hold()
    onCountChanged: hold()

    // glass disc
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: pill.theme.edge
            strokeWidth: 1
            fillGradient: RadialGradient {
                centerX: pill.hubR; centerY: pill.hubR
                centerRadius: pill.hubR
                focalX: pill.hubR * 0.8; focalY: pill.hubR * 0.7
                GradientStop { position: 0.0; color: pill.theme.hubInner }
                GradientStop { position: 1.0; color: pill.theme.hubOuter }
            }
            PathAngleArc {
                centerX: pill.hubR; centerY: pill.hubR
                radiusX: pill.hubR; radiusY: pill.hubR
                startAngle: 0; sweepAngle: 360
            }
        }
    }

    // ---- parked file: thumbnail (images) or document icon (PDFs) ----
    Item {
        id: thumb
        width: Math.round(pill.hubR * 0.62)
        height: width
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -pill.hubR * 0.26
        opacity: pill.parked ? 1 : 0
        scale: pill.parked ? 1 : 0.6
        visible: opacity > 0
        onVisibleChanged: if (!visible) { pill.heldSource = ""; pill.heldLabel = ""; pill.heldCount = 0 }
        Behavior on opacity {
            NumberAnimation { duration: pill.theme.d(pill.theme.fadeMs); easing.type: Easing.OutCubic }
        }
        Behavior on scale {
            NumberAnimation { duration: pill.theme.d(pill.theme.switchMs); easing.type: Easing.OutBack }
        }

        readonly property bool imageReady: pill.heldSource !== "" && img.status === Image.Ready
        // Images skip the icon while loading; PDFs keep it until their
        // rendered page is ready, then crossfade.
        readonly property bool showIcon: pill.heldSource === "" || img.status === Image.Error
                                         || (pill.heldLabel === "PDF" && !imageReady)

        // A batch: two cards fanned out up-right behind the first file
        // (back to front).
        Repeater {
            model: pill.heldCount > 1 ? [2, 1] : []
            delegate: Rectangle {
                required property int modelData
                width: thumb.width
                height: thumb.height
                x: modelData * thumb.width * 0.09
                y: -modelData * thumb.width * 0.07
                rotation: modelData * 5
                radius: 6
                color: modelData === 2 ? pill.theme.pillBottom : pill.theme.pillTop
                border.color: Qt.alpha(pill.theme.ink, 0.30)
                border.width: 1
            }
        }

        Rectangle {
            anchors.fill: parent
            visible: opacity > 0
            opacity: thumb.imageReady ? 1 : 0
            Behavior on opacity {
                NumberAnimation { duration: pill.theme.d(pill.theme.fadeMs * 1.5); easing.type: Easing.OutCubic }
            }
            radius: 6
            color: pill.theme.pillTop
            border.color: pill.theme.edge
            border.width: 1

            // Decoded on Qt's image-loader thread at thumbnail size, so even
            // a huge photo doesn't block the UI.
            Image {
                id: img
                anchors.fill: parent
                anchors.margins: 2
                source: pill.heldSource
                sourceSize.width: parent.width * 2
                sourceSize.height: parent.height * 2
                asynchronous: true
                cache: false
                fillMode: Image.PreserveAspectCrop
                // Documents: show the top of the page (title, header);
                // photos: the middle.
                verticalAlignment: pill.heldLabel === "PDF" ? Image.AlignTop : Image.AlignVCenter
                clip: true
                smooth: true
            }
        }

        // Document icon: PDFs (until their page is rendered), or an image
        // Qt couldn't decode.
        Item {
            anchors.fill: parent
            opacity: thumb.showIcon ? 1 : 0
            visible: opacity > 0
            Behavior on opacity {
                NumberAnimation { duration: pill.theme.d(pill.theme.fadeMs * 1.5); easing.type: Easing.OutCubic }
            }

            Shape {
                width: 24
                height: 24
                scale: parent.width / 24
                transformOrigin: Item.TopLeft
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    fillColor: pill.theme.pillTop
                    strokeColor: pill.theme.ink
                    strokeWidth: 1.4
                    joinStyle: ShapePath.RoundJoin
                    PathSvg { path: "M6.5 2h8l5 5v13a2 2 0 0 1-2 2h-11a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z" }
                }
                ShapePath {
                    fillColor: "transparent"
                    strokeColor: pill.theme.ink
                    strokeWidth: 1.4
                    joinStyle: ShapePath.RoundJoin
                    PathSvg { path: "M14.5 2v5h5" }
                }
            }

            Text {
                textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: parent.height * 0.14
                text: pill.heldLabel
                color: pill.theme.ink
                font.pixelSize: Math.max(7, Math.round(pill.hubR * 0.13))
                font.weight: Font.Bold
            }
        }
    }

    // count badge on the stack's top-right corner
    Rectangle {
        id: badge
        visible: pill.heldCount > 1 && thumb.visible
        opacity: thumb.opacity
        scale: thumb.scale
        height: Math.max(14, Math.round(pill.hubR * 0.30))
        width: Math.max(height, badgeText.implicitWidth + height * 0.5)
        radius: height / 2
        x: thumb.x + thumb.width - width * 0.55
        y: thumb.y - height * 0.40
        color: pill.theme.hotOuter
        border.color: pill.theme.inkHot
        border.width: 1.5
        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            id: badgeText
            anchors.centerIn: parent
            text: pill.heldCount > 99 ? "99+" : pill.heldCount
            color: pill.theme.inkHot
            font.pixelSize: Math.round(badge.height * 0.58)
            font.weight: Font.Bold
        }
    }

    // × on the stack's top-left corner: clears the parked files
    Rectangle {
        id: clearButton
        objectName: "clearStack"
        visible: pill.canClear && thumb.visible
        opacity: thumb.opacity
        scale: thumb.scale * (clearArea.pressed ? 0.9 : 1.0)
        width: Math.max(14, Math.round(pill.hubR * 0.27))
        height: width
        radius: width / 2
        x: thumb.x - width * 0.45
        y: thumb.y - height * 0.40
        color: clearArea.containsMouse ? pill.theme.cancelTop : pill.theme.pillTop
        border.color: clearArea.containsMouse ? pill.theme.cancelBorder : Qt.alpha(pill.theme.ink, 0.35)
        border.width: 1
        Behavior on color { ColorAnimation { duration: pill.theme.d(pill.theme.hoverMs) } }
        Shape {
            anchors.centerIn: parent
            width: parent.width * 0.42
            height: width
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: clearArea.containsMouse ? pill.theme.cancelInk : pill.theme.ink
                strokeWidth: Math.max(1.2, clearButton.width * 0.09)
                capStyle: ShapePath.RoundCap
                fillColor: "transparent"
                PathMove { x: 0; y: 0 }
                PathLine { x: clearButton.width * 0.42; y: clearButton.width * 0.42 }
                PathMove { x: clearButton.width * 0.42; y: 0 }
                PathLine { x: 0; y: clearButton.width * 0.42 }
            }
        }
        MouseArea {
            id: clearArea
            anchors.fill: parent
            anchors.margins: -4  // a little easier to hit
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: pill.clearClicked()
        }
    }

    // ---- pill ----
    Rectangle {
        id: body
        anchors.centerIn: parent
        // slides down to make room for the parked file
        anchors.verticalCenterOffset: pill.parked ? pill.hubR * 0.36 : 0
        Behavior on anchors.verticalCenterOffset {
            NumberAnimation { duration: pill.theme.d(pill.theme.switchMs * 0.8); easing.type: Easing.OutCubic }
        }
        height: Math.round(pill.hubR * 0.48)
        radius: height / 2
        readonly property real maxWidth: pill.hubR * (pill.parked ? 1.70 : 1.78)
        width: pill.entry ? maxWidth : Math.min(maxWidth, Math.max(height * 1.6, metrics.advanceWidth + height * 0.9))
        border.color: pill.entry ? (pill.entryError !== "" ? pill.theme.warnBorder : pill.theme.hotOuter)
                    : pill.danger ? pill.theme.cancelBorder : pill.warn ? pill.theme.warnBorder : pill.theme.pillBorder
        border.width: pill.entry ? 1.5 : 1
        gradient: Gradient {
            GradientStop {
                position: 0.0
                color: pill.topColor
                Behavior on color { ColorAnimation { duration: pill.theme.d(pill.theme.fadeMs); easing.type: Easing.OutCubic } }
            }
            GradientStop {
                position: 1.0
                color: pill.bottomColor
                Behavior on color { ColorAnimation { duration: pill.theme.d(pill.theme.fadeMs); easing.type: Easing.OutCubic } }
            }
        }
        Behavior on width {
            NumberAnimation { duration: pill.theme.d(pill.theme.hoverMs); easing.type: Easing.OutCubic }
        }

        // Long labels ("Scroll to switch") shrink to fit instead of eliding.
        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            id: textA
            anchors.centerIn: parent
            width: Math.min(implicitWidth, body.maxWidth - body.height * 0.6)
            horizontalAlignment: Text.AlignHCenter
            fontSizeMode: Text.HorizontalFit
            minimumPixelSize: Math.round(pill.hubR * 0.16)
            elide: Text.ElideRight
            color: pill.inkColor
            Behavior on color { ColorAnimation { duration: pill.theme.d(pill.theme.fadeMs) } }
            font.pixelSize: Math.round(pill.hubR * 0.22)
            font.weight: Font.DemiBold
        }
        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            id: textB
            anchors.centerIn: parent
            width: Math.min(implicitWidth, body.maxWidth - body.height * 0.6)
            horizontalAlignment: Text.AlignHCenter
            fontSizeMode: Text.HorizontalFit
            minimumPixelSize: textA.minimumPixelSize
            elide: Text.ElideRight
            color: textA.color
            font: textA.font
            opacity: 0
        }

        // Compress > Custom: a number and a KB / MB switch.
        Item {
            id: entryBox
            anchors.fill: parent
            opacity: pill.entry ? 1 : 0
            visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: pill.theme.d(pill.theme.fadeMs); easing.type: Easing.OutCubic } }

            TextInput {
                id: sizeField
                objectName: "sizeField"
                anchors.left: parent.left
                anchors.leftMargin: body.height * 0.45
                anchors.right: unitChip.left
                anchors.rightMargin: body.height * 0.18
                anchors.verticalCenter: parent.verticalCenter
                horizontalAlignment: TextInput.AlignRight
                color: pill.theme.ink
                selectionColor: pill.theme.hotOuter
                selectedTextColor: pill.theme.inkHot
                font: textA.font
                enabled: pill.entry
                validator: RegularExpressionValidator { regularExpression: /^\d{0,6}([.,]\d{0,2})?$/ }
                inputMethodHints: Qt.ImhFormattedNumbersOnly
                onTextChanged: pill.entryError = ""
                Keys.onReturnPressed: pill.submit()
                Keys.onEnterPressed: pill.submit()
                Keys.onEscapePressed: pill.entryCanceled()
                Keys.onTabPressed: pill.unit = pill.unit === "KB" ? "MB" : "KB"
                Keys.onUpPressed: pill.unit = "MB"
                Keys.onDownPressed: pill.unit = "KB"
            }
            Text { textFormat: Text.PlainText;  // placeholder, or why the size can't be used
                anchors.fill: sizeField
                horizontalAlignment: Text.AlignRight
                verticalAlignment: Text.AlignVCenter
                visible: sizeField.text === ""
                text: pill.entryError !== "" ? pill.entryError : "Size"
                color: pill.entryError !== "" ? pill.theme.warnInk : Qt.alpha(pill.theme.ink, 0.45)
                font.pixelSize: Math.round(pill.hubR * (pill.entryError !== "" ? 0.15 : 0.20))
                font.weight: Font.DemiBold
                fontSizeMode: Text.HorizontalFit
                minimumPixelSize: 7
            }
            Rectangle {
                id: unitChip
                anchors.right: parent.right
                anchors.rightMargin: body.height * 0.16
                anchors.verticalCenter: parent.verticalCenter
                height: body.height * 0.68
                width: unitText.implicitWidth + height * 0.7
                radius: height / 2
                color: unitArea.containsMouse ? pill.theme.hotInner : pill.theme.hotOuter
                Behavior on color { ColorAnimation { duration: pill.theme.d(pill.theme.hoverMs) } }
                Text {
                    textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                    id: unitText
                    anchors.centerIn: parent
                    text: pill.unit
                    color: pill.theme.inkHot
                    font.pixelSize: Math.round(pill.hubR * 0.16)
                    font.weight: Font.Bold
                }
                MouseArea {
                    id: unitArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        pill.unit = pill.unit === "KB" ? "MB" : "KB"
                        sizeField.forceActiveFocus()
                    }
                }
            }
        }
    }

    TextMetrics {
        id: metrics
        font: textA.font
        text: pill.text
    }

    // ---- crossfade between the two Text items ----
    property bool aFront: true

    Component.onCompleted: textA.text = text

    onTextChanged: {
        const incoming = aFront ? textB : textA
        const outgoing = aFront ? textA : textB
        crossfade.stop()
        incoming.text = text
        fadeIn.target = incoming
        fadeOut.target = outgoing
        crossfade.start()
        aFront = !aFront
    }

    ParallelAnimation {
        id: crossfade
        NumberAnimation {
            id: fadeIn
            property: "opacity"; to: 1
            duration: pill.theme.d(pill.theme.fadeMs); easing.type: Easing.OutCubic
        }
        NumberAnimation {
            id: fadeOut
            property: "opacity"; to: 0
            duration: pill.theme.d(pill.theme.fadeMs * 0.8); easing.type: Easing.OutCubic
        }
    }
}
