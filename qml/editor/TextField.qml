import QtQuick
import "."

// A single-line text field with a placeholder and an optional icon.
Rectangle {
    id: field

    property alias text: input.text
    property alias validator: input.validator
    property alias horizontalAlignment: input.horizontalAlignment
    function selectAll() { input.selectAll() }
    property string placeholder
    property string icon
    property bool escapeClears: true  // false: Esc goes to the parent (to cancel an edit)
    readonly property bool inputFocused: input.activeFocus
    signal accepted()

    function focusInput() { input.forceActiveFocus() }

    implicitHeight: 36
    radius: Style.radiusSmall
    color: Style.field
    border.width: input.activeFocus ? 2 : 1
    border.color: input.activeFocus ? Style.accent : Style.panelBorder
    Behavior on border.color { ColorAnimation { duration: Style.d(Style.fadeMs) } }

    Icon {
        id: lead
        visible: field.icon !== ""
        x: 10
        anchors.verticalCenter: parent.verticalCenter
        name: field.icon
        size: 17
        color: Style.inkSoft
    }
    TextInput {
        id: input
        anchors.left: lead.visible ? lead.right : parent.left
        anchors.leftMargin: lead.visible ? 8 : 12
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        color: Style.ink
        font.pixelSize: Style.textSize
        selectByMouse: true
        clip: true
        onAccepted: field.accepted()
        Keys.onEscapePressed: (e) => { if (field.escapeClears && text !== "") { text = ""; e.accepted = true } else e.accepted = false }
    }
    Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        anchors.fill: input
        verticalAlignment: Text.AlignVCenter
        visible: input.text === "" && !input.activeFocus
        text: field.placeholder
        color: Style.inkFaint
        font.pixelSize: Style.textSize
        elide: Text.ElideRight
    }
}
