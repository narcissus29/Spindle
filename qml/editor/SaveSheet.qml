import QtQuick
import "."

// "Save a copy": shows the name the new file gets. The original is never
// changed. PDFs with annotations can have them flattened into the page.
Sheet {
    id: sheet

    property bool closeAfter: false  // opened from "Discard changes?"
    property bool flatten: false
    property bool keepLocation: false  // off by default, every time the sheet opens
    property bool limitOn: false
    property string limitUnit: "KB"
    property string limitError: ""
    function applyLimit() {
        limitError = limitOn ? editor.setSaveLimit(limitField.text + " " + limitUnit) : editor.setSaveLimit("")
    }
    signal saveRequested()

    Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        text: "Save a copy"
        color: Style.ink
        font.pixelSize: Style.titleSize + 3
        font.weight: Font.DemiBold
    }

    Rectangle {
        width: parent.width
        height: 64
        radius: Style.radius
        color: Style.field
        border.width: 1
        border.color: Style.divider
        Row {
            x: 14
            anchors.verticalCenter: parent.verticalCenter
            spacing: 12
            Icon { anchors.verticalCenter: parent.verticalCenter; name: "folder"; size: 22; color: Style.accent }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                Text {
                    textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                    width: sheet.cardWidth - 48 - 70
                    text: editor.outputName
                    color: Style.ink
                    font.pixelSize: Style.textSize + 1
                    font.weight: Font.DemiBold
                    elide: Text.ElideMiddle
                }
                Text {
                    textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                    width: sheet.cardWidth - 48 - 70
                    text: "next to the original, in " + editor.folder
                    color: Style.inkSoft
                    font.pixelSize: Style.smallSize
                    elide: Text.ElideMiddle
                }
            }
        }
    }

    Column {
        visible: editor.isPdf && editor.hasMarks
        width: parent.width
        spacing: 4
        CheckBox {
            text: "Flatten annotations"
            checked: sheet.flatten
            onToggled: (on) => sheet.flatten = on
        }
        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            x: 26
            width: parent.width - 26
            text: sheet.flatten ? "Your annotations become part of the page and can't be edited or removed later."
                                : "Your annotations stay editable in other PDF apps."
            color: Style.inkSoft
            font.pixelSize: Style.smallSize
            wrapMode: Text.WordWrap
        }
    }

    Rectangle {
        visible: editor.redactionCount > 0
        width: parent.width
        height: redactNote.implicitHeight + 18
        radius: Style.radiusSmall
        color: Style.dangerSoft
        Row {
            x: 10
            y: 9
            spacing: 8
            Icon { name: "redact"; size: 16; color: Style.danger }
            Text {
                textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                id: redactNote
                width: sheet.cardWidth - 48 - 44
                text: editor.redactionCount + (editor.redactionCount === 1 ? " area is" : " areas are")
                      + " redacted for good in the copy" + (editor.isPdf ? " (the text under " + (editor.redactionCount === 1 ? "it" : "them") + " is deleted, also from bookmark titles)" : "")
                      + ", and it is saved without metadata.\nThe file name isn't redacted. Rename it if it contains sensitive info."
                color: Style.danger
                font.pixelSize: Style.smallSize
                wrapMode: Text.WordWrap
            }
        }
    }

    Column {  // "Limit file size": for upload forms ("max 50 KB")
        width: parent.width
        spacing: 6
        CheckBox {
            objectName: "limitBox"
            text: "Limit file size"
            checked: sheet.limitOn
            onToggled: (on) => { sheet.limitOn = on; sheet.applyLimit() }
        }
        Row {
            visible: sheet.limitOn
            x: 26
            spacing: 6
            TextField {
                id: limitField
                objectName: "limitField"
                width: 90
                implicitHeight: 32
                horizontalAlignment: TextInput.AlignRight
                validator: RegularExpressionValidator { regularExpression: /^\d{0,6}([.,]\d{0,2})?$/ }
                text: "100"
                onTextChanged: if (sheet.limitOn) sheet.applyLimit()
            }
            Chip { anchors.verticalCenter: parent.verticalCenter; text: "KB"; checked: sheet.limitUnit === "KB"; onClicked: { sheet.limitUnit = "KB"; sheet.applyLimit() } }
            Chip { anchors.verticalCenter: parent.verticalCenter; text: "MB"; checked: sheet.limitUnit === "MB"; onClicked: { sheet.limitUnit = "MB"; sheet.applyLimit() } }
        }
        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            visible: sheet.limitOn
            x: 26
            width: parent.width - 26
            text: sheet.limitError !== "" ? "Use a size from " + sheet.limitError
                  : editor.isPdf ? "Images inside are made smaller step by step until it fits."
                  : "Saved at the best quality that fits (as JPG, WEBP stays WEBP), without metadata."
            color: sheet.limitError !== "" ? Style.danger : Style.inkSoft
            font.pixelSize: Style.smallSize
            wrapMode: Text.WordWrap
        }
    }

    Column {  // an edited photo leaves its GPS position out unless asked
        visible: editor.locationChoice
        width: parent.width
        spacing: 4
        CheckBox {
            text: "Keep location"
            checked: sheet.keepLocation
            onToggled: (on) => sheet.keepLocation = on
        }
        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            x: 26
            width: parent.width - 26
            text: sheet.keepLocation ? "The copy keeps where the photo was taken (GPS)."
                                     : "The copy leaves out where the photo was taken. Camera details and dates are kept."
            color: Style.inkSoft
            font.pixelSize: Style.smallSize
            wrapMode: Text.WordWrap
        }
    }

    Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        width: parent.width
        text: "The original file is not changed."
        color: Style.inkSoft
        font.pixelSize: Style.smallSize
        wrapMode: Text.WordWrap
    }

    Item {
        width: parent.width
        height: 40
        Row {
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            spacing: 8
            PillButton { text: "Cancel"; onClicked: { sheet.closeAfter = false; sheet.close() } }
            PillButton {
                primary: true
                icon: "save"
                text: editor.saving ? "Saving…" : "Save"
                busy: editor.saving
                onClicked: sheet.saveRequested()
            }
        }
    }

    Shortcut {
        sequences: ["Return", "Enter", StandardKey.Save]
        enabled: sheet.shown && !editor.saving
        onActivated: sheet.saveRequested()
    }
    onCanceled: closeAfter = false
    onShownChanged: if (shown) { keepLocation = false; editor.loadMeta() }  // for "Keep location"
}
