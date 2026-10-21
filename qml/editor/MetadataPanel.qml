import QtQuick
import "."

// Info: everything the file carries besides the picture / pages, with a
// prominent "Remove all". Single entries can be edited or removed; all
// changes are undoable and written when the copy is saved.
PanelPage {
    id: panel

    tool: "metadata"
    title: "Info"
    subtitle: editor.isPdf ? "What the document says about itself and its author."
                           : "What the photo says about itself: where, when, with what."

    signal viewRequested(string key)

    readonly property bool ready: editor.metaStatus === "ready"

    // ---- the big card: Remove all / Save clean copy / nothing to remove ----
    Rectangle {
        id: hero
        width: parent.width
        height: heroCol.implicitHeight + 28
        radius: Style.radius
        color: !panel.ready ? Style.field : (editor.metaClean || !editor.metaAny ? Style.field : Style.accentSoft)
        border.width: 1
        border.color: !panel.ready || editor.metaClean || !editor.metaAny ? Style.divider : Style.accentLine
        Behavior on color { ColorAnimation { duration: Style.d(Style.panelMs) } }
        Behavior on height { NumberAnimation { duration: Style.d(Style.panelMs); easing.type: Easing.OutCubic } }
        clip: true

        Column {
            id: heroCol
            x: 14
            y: 14
            width: parent.width - 28
            spacing: 10

            Row {
                width: parent.width
                spacing: 10
                Item {
                    width: 24
                    height: 24
                    Spinner { anchors.centerIn: parent; visible: !panel.ready && editor.metaStatus !== "failed"; color: Style.accent }
                    Icon {
                        anchors.centerIn: parent
                        visible: panel.ready || editor.metaStatus === "failed"
                        name: editor.metaStatus === "failed" ? "info" : (editor.metaClean || !editor.metaAny ? "check" : "shield")
                        size: 24
                        color: editor.metaStatus === "failed" ? Style.danger : Style.accent
                    }
                }
                Column {
                    width: parent.width - 34
                    spacing: 3
                    Text {
                        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                        width: parent.width
                        text: editor.metaStatus === "failed" ? editor.metaError
                              : !panel.ready ? "Reading metadata…"
                              : !editor.metaAny ? "No metadata found"
                              : editor.metaClean ? "Everything will be removed"
                              : "Remove all metadata"
                        color: Style.ink
                        font.pixelSize: Style.textSize + 1
                        font.weight: Font.DemiBold
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                        visible: panel.ready
                        width: parent.width
                        text: !editor.metaAny ? (editor.isPdf ? "This document doesn't say who made it or with what."
                                                              : "This picture carries no location, camera or other details.")
                              : editor.metaClean ? "Save the copy to finish. The original stays as it is."
                              : editor.isPdf ? "Author, apps, dates, comment authors, hidden data and the details inside photos. Pages aren't changed."
                              : "Location, camera, dates and everything else. The picture isn't re-encoded."
                        color: Style.inkSoft
                        font.pixelSize: Style.smallSize
                        wrapMode: Text.WordWrap
                    }
                }
            }

            PillButton {
                visible: panel.ready && editor.metaAny && !editor.metaClean
                width: parent.width
                primary: true
                icon: "shield"
                text: "Remove all"
                onClicked: editor.removeAllMeta()
            }
            Row {
                visible: panel.ready && editor.metaClean
                width: parent.width
                spacing: 8
                PillButton {
                    width: parent.width - undoAll.width - 8
                    primary: true
                    icon: "save"
                    text: editor.saving ? "Saving…" : "Save clean copy"
                    busy: editor.saving
                    onClicked: editor.save(false)
                }
                PillButton {
                    id: undoAll
                    text: "Undo"
                    enabled: editor.canUndo
                    onClicked: editor.undo()
                }
            }
        }
    }

    Text { textFormat: Text.PlainText;  // why single entries can't be changed (TIFF, GIF, BMP)
        visible: panel.ready && editor.metaNote !== ""
        width: parent.width
        text: editor.metaNote
        color: Style.inkSoft
        font.pixelSize: Style.smallSize
        wrapMode: Text.WordWrap
    }

    // ---- every entry, by section ----
    // The repeaters count rows instead of taking the list itself, so a
    // change updates rows in place (no rebuild, the scroll stays put).
    Item {
        id: listBox
        visible: panel.ready
        clip: true
        width: parent.width + 16
        x: -8
        height: Math.max(60, panel.height - panel.bodyTop - y - 14)
        opacity: panel.ready ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Style.d(Style.panelMs) } }

        Flickable {
            id: list
            objectName: "metaList"
            anchors.fill: parent
            contentHeight: sections.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            Column {
                id: sections
                x: 8
                width: list.width - 16 - (scrollbar.visible ? 4 : 0)
                spacing: 4

                Repeater {
                    model: editor.metaSections.length
                    Column {
                        id: section
                        required property int index
                        readonly property var entry: editor.metaSections[index]
                        width: sections.width
                        spacing: 0
                        Item { width: 1; height: 8 }
                        SectionLabel { text: section.entry ? section.entry.title : "" }
                        Item { width: 1; height: 2 }
                        Repeater {
                            model: section.entry ? section.entry.items.length : 0
                            MetaRow {
                                required property int index
                                item: section.entry.items[index] || ({ key: "", label: "", value: "", edit: "", removable: false, state: "", hint: "", covered: false })
                                onViewRequested: (key) => panel.viewRequested(key)
                            }
                        }
                    }
                }
                Item { width: 1; height: 8 }
            }
        }

        Rectangle {  // slim scroll indicator
            id: scrollbar
            visible: list.contentHeight > list.height + 1
            x: listBox.width - 6
            y: list.visibleArea.yPosition * list.height
            width: 4
            height: Math.max(24, list.visibleArea.heightRatio * list.height)
            radius: 2
            color: Style.inkFaint
            opacity: list.moving ? 0.9 : 0.45
            Behavior on opacity { NumberAnimation { duration: Style.d(Style.fadeMs) } }
        }
    }
}
