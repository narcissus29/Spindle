import QtQuick
import QtQuick.Window
import "../editor"
import "."

// Settings: shortcut, start at login, look, compress strength, tray icon,
// troubleshooting, and (Linux AppImage) removing Spindle. Every change is
// saved at once and the running wheel picks it up.
Window {
    id: win

    width: 600
    height: 720
    minimumWidth: 520
    minimumHeight: 520
    visible: true
    color: Style.windowBg
    title: "Spindle Settings"

    component Section: Column {
        property string title
        width: list.width - 72
        x: 36
        spacing: 10
        SectionLabel { text: parent.title }
    }
    component Note: Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        width: parent ? parent.width : 300
        wrapMode: Text.WordWrap
        color: Style.inkSoft
        font.pixelSize: Style.smallSize
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 16
        radius: Style.radius + 4
        color: Style.panel
        border.width: 1
        border.color: Style.panelBorder
        clip: true

        Flickable {
            id: list
            anchors.fill: parent
            contentHeight: content.implicitHeight + 48
            boundsBehavior: Flickable.StopAtBounds

            Column {
                id: content
                y: 28
                width: list.width
                spacing: 26

                Row {
                    x: 36
                    spacing: 12
                    Image { source: "../../assets/brand/icon-48.png"; smooth: false; width: 48; height: 48 }
                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        Text { textFormat: Text.PlainText; text: "Settings"; color: Style.ink; font.pixelSize: 22; font.weight: Font.DemiBold }
                        Text { textFormat: Text.PlainText; text: "Spindle " + setup.version; color: Style.inkSoft; font.pixelSize: Style.smallSize }
                    }
                }

                Section {
                    title: "Shortcut"
                    ShortcutField { id: shortcutField; visible: setup.shortcutMode !== "manual" }
                    Note {
                        visible: text !== ""
                        color: shortcutField.status === "error" ? Style.danger : Style.accent
                        font.pixelSize: Style.smallSize + 1
                        text: shortcutField.status === "error" ? setup.error : shortcutField.status === "ok" ? "✓ Set." : ""
                    }
                    Note {
                        objectName: "shortcutWarning"
                        visible: text !== "" && !shortcutField.recording && shortcutField.status !== "error"
                        text: setup.shortcutWarning
                    }
                    Row {
                        visible: setup.shortcutMode !== "manual" && !shortcutField.recording
                                 && setup.shortcut !== setup.defaultShortcut
                                 && (setup.shortcutProblem || setup.shortcutWarning !== "")
                        spacing: 10
                        Text { textFormat: Text.PlainText; anchors.verticalCenter: parent.verticalCenter; text: "Or use"; color: Style.inkSoft; font.pixelSize: Style.textSize }
                        PillButton {
                            text: setup.pretty(setup.defaultShortcut)
                            onClicked: shortcutField.status = setup.setShortcut(setup.defaultShortcut) ? "ok" : "error"
                        }
                    }
                    Note {
                        visible: setup.shortcutMode === "manual"
                        text: "Add this command as a custom shortcut in your desktop's keyboard settings:"
                    }
                    Row {
                        visible: setup.shortcutMode === "manual"
                        spacing: 8
                        Text {
                            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                            width: list.width - 72 - 90
                            anchors.verticalCenter: parent.verticalCenter
                            text: setup.manualCommand
                            color: Style.ink
                            font.family: "monospace"
                            font.pixelSize: Style.smallSize
                            wrapMode: Text.WrapAnywhere
                        }
                        PillButton { text: "Copy"; onClicked: setup.copyText(setup.manualCommand) }
                    }
                }

                Section {
                    title: "Start"
                    Toggle {
                        text: "Start Spindle when I log in"
                        checked: setup.autostart
                        onToggled: (on) => setup.setAutostart(on)
                    }
                    Toggle {
                        text: "Show an icon in the " + (setup.isWindows ? "system tray" : "top bar")
                        checked: setup.trayIcon
                        onToggled: (on) => setup.setTrayIcon(on)
                    }
                    Note {
                        visible: !setup.isWindows
                        text: "On GNOME the icon needs the AppIndicator extension (Ubuntu has it). Without it, open Settings from the app grid: right-click Spindle."
                    }
                }

                Section {
                    title: "Look"
                    Row {
                        spacing: 6
                        Chip { text: "Blue"; checked: setup.theme === "blue"; onClicked: setup.setTheme("blue") }
                        Chip { text: "Orange"; checked: setup.theme === "orange"; onClicked: setup.setTheme("orange") }
                    }
                    Toggle {
                        text: "Reduce motion"
                        checked: setup.reduceAnimations
                        onToggled: (on) => setup.setReduceAnimations(on)
                    }
                }

                Section {
                    title: "Compress (one click)"
                    Row {
                        spacing: 6
                        Chip { text: "Light"; checked: setup.compressPreset === "light"; onClicked: setup.setCompressPreset("light") }
                        Chip { text: "Balanced"; checked: setup.compressPreset === "balanced"; onClicked: setup.setCompressPreset("balanced") }
                        Chip { text: "Strong"; checked: setup.compressPreset === "strong"; onClicked: setup.setCompressPreset("strong") }
                    }
                    Note {
                        text: setup.compressPreset === "light" ? "Only lossless savings: the pictures stay exactly the same."
                            : setup.compressPreset === "strong" ? "The smallest files: photos at lower quality, big images scaled down."
                            : "Smaller photos that still look the same at a glance. Screenshots and drawings in PDFs stay sharp."
                    }
                    Note { text: "For a set size (\"under 50 KB\"), park the file on the wheel's center and click Compress." }
                }

                Section {
                    title: "Troubleshooting"
                    Toggle {
                        text: "Draw without the graphics card"
                        checked: setup.softwareRendering
                        onToggled: (on) => setup.setSoftwareRendering(on)
                    }
                    Note { text: "Try this if the wheel flickers or doesn't show. Spindle restarts to apply it." }
                    Item { width: 1; height: 4 }
                    PillButton {
                        objectName: "openLogs"
                        text: "Open log folder"
                        onClicked: setup.openLogFolder()
                    }
                    Note { text: "Something went wrong? spindle.log in " + setup.logFolder + " says what happened." }
                }

                Section {
                    title: "Remove Spindle"
                    visible: setup.isAppImage
                    Note { text: "Removes the app from " + setup.installedPath + ", the app-menu entry, the shortcut and starting at login." }
                    CheckBox { id: alsoSettings; text: "Also delete my settings" }
                    PillButton {
                        id: removeButton
                        danger: true
                        icon: "trash"
                        property bool armed: false
                        text: armed ? "Click again to remove Spindle" : "Remove Spindle"
                        onClicked: armed ? setup.removeSpindle(alsoSettings.checked) : (armed = true)
                    }
                }

                Note {
                    x: 36
                    width: list.width - 72
                    text: "Spindle is free software under the GNU AGPL-3.0."
                }
            }
        }
    }

    Shortcut { sequence: "Esc"; enabled: !shortcutField.recording; onActivated: win.close() }
}
