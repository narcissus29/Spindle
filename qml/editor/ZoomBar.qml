import QtQuick
import "."

// − 100% + and fit, floating over the canvas corner.
Rectangle {
    id: zb

    required property Item vp

    width: row.implicitWidth + 8
    height: 40
    radius: 20
    color: Style.panel
    border.width: 1
    border.color: Style.panelBorder

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 0
        IconButton { size: 32; iconSize: 18; icon: "zoom-out"; tip: "Zoom out  (Ctrl+−)"; tipSide: "above"; onClicked: zb.vp.zoomOut() }
        Item {
            width: 54
            height: 32
            Text {
                textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                anchors.centerIn: parent
                text: Math.round(zb.vp.percent) + "%"
                color: Style.ink
                font.pixelSize: Style.smallSize
                font.features: { "tnum": 1 }
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: zb.vp.actualSize()
            }
        }
        IconButton { size: 32; iconSize: 18; icon: "zoom-in"; tip: "Zoom in  (Ctrl++)"; tipSide: "above"; onClicked: zb.vp.zoomIn() }
        IconButton { size: 32; iconSize: 18; icon: "fit"; tip: "Fit  (F)"; tipSide: "above"; onClicked: zb.vp.fit() }
    }
}
