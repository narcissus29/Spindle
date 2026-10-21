import QtQuick
import QtQuick.Window
import "../editor"
import "."

// First run: 1) the shortcut, 2) start at login, 3) how to use it.
// Steps slide sideways; Next / Back / Done at the bottom.
Window {
    id: win

    width: 620
    height: 600
    minimumWidth: 560
    minimumHeight: 560
    visible: true
    color: Style.windowBg
    title: "Welcome to Spindle"

    property int step: 0
    property bool startAtLogin: true
    readonly property int steps: 3

    function next() {
        if (step === 1)
            setup.setAutostart(startAtLogin)
        if (step < steps - 1)
            step += 1
        else
            setup.finishWelcome()
    }

    Rectangle {
        id: card
        anchors.fill: parent
        anchors.margins: 16
        radius: Style.radius + 4
        color: Style.panel
        border.width: 1
        border.color: Style.panelBorder
        clip: true

        // ---- the steps, side by side; the row slides ----
        Row {
            id: track
            y: 0
            height: parent.height - footer.height
            x: -win.step * card.width
            Behavior on x { NumberAnimation { duration: Style.d(Style.revealMs); easing.type: Easing.OutCubic } }

            // 1. Welcome + shortcut
            Item {
                width: card.width
                height: track.height
                opacity: win.step === 0 ? 1 : 0.3
                Behavior on opacity { NumberAnimation { duration: Style.d(Style.revealMs) } }
                Column {
                    x: 36
                    y: 32
                    width: parent.width - 72
                    spacing: 14
                    Row {
                        spacing: 14
                        Image {  // the logo on its dark tile (pixel art: never smoothed)
                            source: "../../assets/brand/logo-tile-96.png"
                            smooth: false
                            width: 96
                            height: 96
                        }
                        Column {
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 3
                            Text { textFormat: Text.PlainText; text: "Welcome to Spindle"; color: Style.ink; font.pixelSize: 24; font.weight: Font.DemiBold }
                            Text { textFormat: Text.PlainText; text: "Convert, compress and edit files from a wheel."; color: Style.inkSoft; font.pixelSize: Style.textSize }
                        }
                    }
                    Rectangle {  // the AppImage put itself in ~/Applications
                        visible: setup.isAppImage
                        width: parent.width
                        height: installNote.implicitHeight + 20
                        radius: Style.radiusSmall
                        color: Style.accentSoft
                        border.width: 1
                        border.color: Style.accentLine
                        Row {
                            x: 12
                            y: 10
                            spacing: 10
                            Icon { name: "check"; size: 18; color: Style.accent }
                            Text {
                                textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                                id: installNote
                                width: card.width - 72 - 60
                                text: "Spindle installed itself to " + setup.installedPath
                                      + " and is in your apps now. You can delete the downloaded file. "
                                      + "To remove Spindle later: Settings → Remove Spindle."
                                color: Style.ink
                                font.pixelSize: Style.smallSize + 1
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                    Item { width: 1; height: 4 }
                    Text {
                        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                        text: setup.shortcutMode === "manual" ? "Your shortcut" : "Press the shortcut you want"
                        color: Style.ink
                        font.pixelSize: Style.titleSize + 2
                        font.weight: Font.DemiBold
                    }
                    Text {
                        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                        width: parent.width
                        wrapMode: Text.WordWrap
                        color: Style.inkSoft
                        font.pixelSize: Style.textSize
                        text: "It opens the wheel, also while you drag a file. "
                              + (setup.shortcutMode === "gnome" ? "Spindle sets it up in GNOME for you."
                                 : setup.shortcutMode === "windows" ? "It works everywhere in Windows."
                                 : "Your desktop doesn't let apps set shortcuts: add the command below as a custom shortcut in its keyboard settings.")
                    }
                    ShortcutField {
                        id: shortcutField
                        objectName: "shortcutField"
                        visible: setup.shortcutMode !== "manual"
                    }
                    Text { textFormat: Text.PlainText;  // why that one didn't work, or that it did
                        width: parent.width
                        visible: setup.shortcutMode !== "manual" && text !== ""
                        wrapMode: Text.WordWrap
                        font.pixelSize: Style.smallSize + 1
                        color: shortcutField.status === "error" ? Style.danger : Style.accent
                        text: shortcutField.status === "error" ? setup.error
                              : shortcutField.status === "ok" ? "✓ Set. Try it any time." : ""
                    }
                    Text {  // a shortcut that works but may misbehave
                        textFormat: Text.PlainText
                        objectName: "shortcutWarning"
                        width: parent.width
                        visible: text !== "" && !shortcutField.recording && shortcutField.status !== "error"
                        wrapMode: Text.WordWrap
                        font.pixelSize: Style.smallSize + 1
                        color: Style.inkSoft
                        text: setup.shortcutWarning
                    }
                    Row {  // one click for the usual choice
                        visible: setup.shortcutMode !== "manual" && !shortcutField.recording
                                 && setup.shortcut !== setup.defaultShortcut
                                 && (setup.shortcut === "" || setup.shortcutProblem || setup.shortcutWarning !== "")
                        spacing: 10
                        Text { textFormat: Text.PlainText; anchors.verticalCenter: parent.verticalCenter; text: "Or use"; color: Style.inkSoft; font.pixelSize: Style.textSize }
                        PillButton {
                            text: setup.pretty(setup.defaultShortcut)
                            onClicked: shortcutField.status = setup.setShortcut(setup.defaultShortcut) ? "ok" : "error"
                        }
                    }
                    Rectangle {  // other desktops: the command to bind
                        visible: setup.shortcutMode === "manual"
                        width: parent.width
                        height: cmd.implicitHeight + 24
                        radius: Style.radiusSmall
                        color: Style.field
                        border.width: 1
                        border.color: Style.divider
                        Text {
                            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                            id: cmd
                            x: 12
                            y: 12
                            width: parent.width - copyButton.width - 36
                            text: setup.manualCommand
                            color: Style.ink
                            font.family: "monospace"
                            font.pixelSize: Style.smallSize
                            wrapMode: Text.WrapAnywhere
                        }
                        PillButton {
                            id: copyButton
                            anchors.right: parent.right
                            anchors.rightMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            text: copied ? "Copied" : "Copy"
                            property bool copied: false
                            onClicked: { setup.copyText(setup.manualCommand); copied = true }
                        }
                    }
                }
            }

            // 2. Start at login
            Item {
                width: card.width
                height: track.height
                opacity: win.step === 1 ? 1 : 0.3
                Behavior on opacity { NumberAnimation { duration: Style.d(Style.revealMs) } }
                Column {
                    x: 36
                    y: 48
                    width: parent.width - 72
                    spacing: 16
                    Text { textFormat: Text.PlainText; text: "Start Spindle when you log in?"; color: Style.ink; font.pixelSize: 22; font.weight: Font.DemiBold }
                    Text {
                        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                        width: parent.width
                        wrapMode: Text.WordWrap
                        color: Style.inkSoft
                        font.pixelSize: Style.textSize + 1
                        text: "Then the wheel opens instantly when you press the shortcut. Spindle waits quietly: "
                              + "it uses no processor time and very little memory until you need it."
                    }
                    Toggle {
                        objectName: "autostartToggle"
                        text: "Start Spindle when I log in"
                        checked: win.startAtLogin
                        onToggled: (on) => win.startAtLogin = on
                    }
                    Text {
                        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                        width: parent.width
                        wrapMode: Text.WordWrap
                        color: Style.inkSoft
                        font.pixelSize: Style.smallSize
                        text: "You can change this later in Settings."
                    }
                }
            }

            // 3. How to use it
            Item {
                width: card.width
                height: track.height
                opacity: win.step === 2 ? 1 : 0.3
                Behavior on opacity { NumberAnimation { duration: Style.d(Style.revealMs) } }
                Column {
                    x: 36
                    y: 48
                    width: parent.width - 72
                    spacing: 18
                    Text { textFormat: Text.PlainText; text: "How to use it"; color: Style.ink; font.pixelSize: 22; font.weight: Font.DemiBold }
                    Repeater {
                        model: [
                            { n: "1", title: "Grab a file", body: "Start dragging a file (or several) from your file manager or desktop." },
                            { n: "2", title: "Press " + (setup.shortcut !== "" ? setup.pretty(setup.shortcut) : "your shortcut"),
                              body: "The wheel opens where you are, while you still hold the file." },
                            { n: "3", title: "Drop it on what you want", body: "Convert, compress, crop, redact… The new file appears next to the original, which is never changed." },
                        ]
                        Row {
                            required property var modelData
                            spacing: 14
                            Rectangle {
                                width: 34
                                height: 34
                                radius: 17
                                color: Style.accent
                                Text { textFormat: Text.PlainText; anchors.centerIn: parent; text: modelData.n; color: "white"; font.pixelSize: 16; font.weight: Font.Bold }
                            }
                            Column {
                                width: card.width - 72 - 48
                                spacing: 2
                                Text { textFormat: Text.PlainText; text: modelData.title; color: Style.ink; font.pixelSize: Style.titleSize; font.weight: Font.DemiBold }
                                Text { textFormat: Text.PlainText; width: parent.width; text: modelData.body; color: Style.inkSoft; font.pixelSize: Style.textSize; wrapMode: Text.WordWrap }
                            }
                        }
                    }
                    Text {
                        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                        width: parent.width
                        wrapMode: Text.WordWrap
                        color: Style.inkSoft
                        font.pixelSize: Style.smallSize + 1
                        text: "Tip: drop on the center to park the file and choose at leisure. "
                              + "Press the shortcut with nothing in hand and the wheel waits for your file."
                    }
                }
            }
        }

        // ---- footer ----
        Item {
            id: footer
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 72
            Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Style.divider }
            StepDots {
                anchors.left: parent.left
                anchors.leftMargin: 36
                anchors.verticalCenter: parent.verticalCenter
                count: win.steps
                current: win.step
            }
            Row {
                anchors.right: parent.right
                anchors.rightMargin: 24
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                PillButton {
                    text: "Back"
                    visible: win.step > 0
                    onClicked: win.step -= 1
                }
                PillButton {
                    objectName: "nextButton"
                    primary: true
                    text: win.step === win.steps - 1 ? "Start using Spindle" : (win.step === 0 && setup.shortcut === "" && setup.shortcutMode !== "manual" ? "Skip" : "Next")
                    onClicked: win.next()
                }
            }
        }
    }

    Shortcut { sequences: ["Return", "Enter"]; enabled: !shortcutField.recording; onActivated: win.next() }
}
