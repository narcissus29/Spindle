import QtQuick
import "."

// One metadata entry in the Info panel: label, value, and what can be
// done with it (edit, remove, restore, view). Removed entries are struck
// through until the copy is saved; edited ones show the new value.
Item {
    id: row

    required property var item
    property bool editing: false
    property string error: ""

    signal viewRequested(string key)

    readonly property bool removed: item.state === "removed"
    readonly property bool edited: item.state === "edited"
    readonly property bool canEdit: item.edit !== "" && editor.metaEditable
    readonly property bool empty: item.value === "" && !removed

    width: parent ? parent.width : 0
    height: Math.max(col.implicitHeight, 34) + 12

    function startEdit() {
        if (!canEdit) return
        error = ""
        field.text = removed ? "" : item.value
        editing = true
        field.focusInput()
    }
    function commit() {
        if (!editing) return
        const message = editor.setMeta(item.key, field.text)
        if (message !== "") {
            error = message
            field.focusInput()
            return
        }
        error = ""
        editing = false
    }

    Rectangle {  // hover
        anchors.fill: parent
        anchors.leftMargin: -8
        anchors.rightMargin: -8
        radius: Style.radiusSmall
        color: hover.hovered && !row.editing ? Style.hover : Style.clear
        Behavior on color { ColorAnimation { duration: Style.d(Style.hoverMs) } }
    }
    HoverHandler { id: hover }

    Column {
        id: col
        y: 6
        width: parent.width - actions.width - 6
        spacing: 2

        Row {
            spacing: 6
            Text {
                textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                text: row.item.label
                color: Style.inkSoft
                font.pixelSize: 11
                font.weight: Font.DemiBold
            }
            Rectangle {  // "Changed" / "Removed" badge
                visible: row.removed || row.edited
                anchors.verticalCenter: parent.verticalCenter
                width: badge.implicitWidth + 10
                height: 15
                radius: 7.5
                color: row.removed ? Style.dangerSoft : Style.accentSoft
                Text {
                    textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                    id: badge
                    anchors.centerIn: parent
                    text: row.removed ? "Removed" : "Changed"
                    color: row.removed ? Style.danger : Style.accent
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                }
            }
        }

        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            visible: !row.editing
            width: parent.width
            text: row.empty ? (row.canEdit ? "Not set. Click to add" : "Not set") : row.item.value
            color: row.removed || row.empty ? Style.inkFaint : Style.ink
            font.pixelSize: Style.textSize
            font.strikeout: row.removed && !row.empty
            wrapMode: Text.Wrap
            maximumLineCount: 4
            elide: Text.ElideRight
            MouseArea {
                anchors.fill: parent
                enabled: row.canEdit
                cursorShape: row.canEdit ? Qt.IBeamCursor : Qt.ArrowCursor
                onClicked: row.startEdit()
            }
        }

        TextField {
            id: field
            visible: row.editing
            width: parent.width
            implicitHeight: 32
            placeholder: row.item.edit === "date" ? "2024-05-31 18:30"
                         : row.item.edit === "gps" ? "48.8584, 2.2945" : row.item.label
            escapeClears: false
            onAccepted: row.commit()
            Keys.onEscapePressed: (e) => { row.editing = false; row.error = ""; e.accepted = true }
            onInputFocusedChanged: if (!inputFocused && row.editing && row.error === "") row.commit()
        }

        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            visible: row.error !== ""
            width: parent.width
            text: row.error
            color: Style.danger
            font.pixelSize: Style.smallSize
            wrapMode: Text.WordWrap
        }

        Image {  // the EXIF thumbnail, so you can see what it shows
            visible: !!row.item.thumb && !row.removed
            width: Math.min(parent.width, 120)
            height: visible ? width * 0.75 : 0
            fillMode: Image.PreserveAspectFit
            horizontalAlignment: Image.AlignLeft
            asynchronous: true
            source: visible ? "image://doc/exifthumb" : ""
        }

        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            visible: row.item.hint !== "" && !row.editing
            width: parent.width
            text: row.item.hint
            color: Style.inkFaint
            font.pixelSize: 11
            wrapMode: Text.WordWrap
        }
    }

    Row {
        id: actions
        anchors.right: parent.right
        y: 4
        spacing: 0

        IconButton {
            visible: !!row.item.view && !row.removed
            icon: "eye"; size: 28; iconSize: 16
            tip: "View"; tipSide: "left"
            onClicked: row.viewRequested(row.item.key)
        }
        IconButton {
            visible: row.editing
            icon: "check"; size: 28; iconSize: 16
            tip: "Done  (Enter)"; tipSide: "left"
            onClicked: row.commit()
        }
        IconButton {
            visible: row.canEdit && !row.editing
            icon: "pen"; size: 28; iconSize: 16
            tip: row.empty ? "Add" : "Edit"; tipSide: "left"
            onClicked: row.startEdit()
        }
        IconButton {
            visible: row.item.removable && !row.removed && !row.editing && (editor.metaEditable || editor.isPdf)
            icon: "trash"; size: 28; iconSize: 16
            danger: true
            tip: "Remove"; tipSide: "left"
            onClicked: editor.removeMeta(row.item.key)
        }
        IconButton {
            visible: (row.removed || row.edited) && !row.editing && !row.item.covered
            icon: "restore"; size: 28; iconSize: 16
            tip: "Keep the original"; tipSide: "left"
            onClicked: editor.restoreMeta(row.item.key)
        }
    }
}
