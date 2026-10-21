import QtQuick
import "."

PanelPage {
    id: panel

    tool: "redact"
    title: "Redact"
    subtitle: "Drag on the page to cover an area. Click a box to select it, Delete removes it."

    property bool matchCase: false
    property bool wholeWord: false

    function runSearch() {
        editor.search(field.text, matchCase, wholeWord)
    }

    // ---- search and redact (PDFs) ----
    Column {
        visible: editor.isPdf
        width: parent.width
        spacing: 10

        SectionLabel { text: "Find text" }
        Row {
            width: parent.width
            spacing: 6
            TextField {
                id: field
                width: parent.width - findButton.width - 6
                icon: "search"
                placeholder: "Name, number, word…"
                onAccepted: panel.runSearch()
            }
            PillButton {
                id: findButton
                text: "Find"
                enabled: field.text.trim() !== ""
                busy: editor.searching
                onClicked: panel.runSearch()
            }
        }
        Row {
            spacing: 14
            CheckBox { text: "Match case"; checked: panel.matchCase; onToggled: (on) => { panel.matchCase = on; if (editor.searchTerm !== "") panel.runSearch() } }
            CheckBox { text: "Whole words"; checked: panel.wholeWord; onToggled: (on) => { panel.wholeWord = on; if (editor.searchTerm !== "") panel.runSearch() } }
        }

        Text {
            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
            visible: editor.searchTerm !== "" && !editor.searching
            width: parent.width
            wrapMode: Text.WordWrap
            color: editor.searchResults.length ? Style.ink : Style.inkSoft
            font.pixelSize: Style.smallSize
            text: {
                const n = editor.searchResults.length
                if (!n) return "No matches. A scanned PDF has no text to search: draw boxes over it instead."
                const pages = new Set(editor.searchResults.map(r => r.page)).size
                return n + (n === 1 ? " match" : " matches") + " on " + pages + (pages === 1 ? " page" : " pages")
            }
        }

        Rectangle {
            visible: editor.searchResults.length > 0
            width: parent.width
            height: Math.min(results.contentHeight + 2, 236)
            radius: Style.radiusSmall
            color: Style.field
            border.width: 1
            border.color: Style.divider
            clip: true

            ListView {
                id: results
                anchors.fill: parent
                anchors.margins: 1
                model: editor.searchResults
                boundsBehavior: Flickable.StopAtBounds
                delegate: Item {
                    id: row
                    required property var modelData
                    required property int index
                    width: results.width
                    height: 42
                    Rectangle {
                        anchors.fill: parent
                        color: rowArea.containsMouse ? Style.hover : (row.modelData.page === editor.page ? Style.accentSoft : "transparent")
                    }
                    CheckBox {
                        id: tick
                        x: 8
                        anchors.verticalCenter: parent.verticalCenter
                        checked: row.modelData.checked
                        onToggled: (on) => editor.setResultChecked(row.index, on)
                        z: 2
                    }
                    Column {
                        anchors.left: tick.right
                        anchors.leftMargin: 2
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 1
                        Text {
                            textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                            width: parent.width
                            text: "Page " + (row.modelData.page + 1)
                            color: Style.inkSoft
                            font.pixelSize: 10
                        }
                        Text {
                            width: parent.width
                            elide: Text.ElideRight
                            textFormat: Text.StyledText
                            color: Style.ink
                            font.pixelSize: Style.smallSize
                            function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;") }
                            text: esc(row.modelData.context) + "<b>" + esc(row.modelData.text) + "</b>" + esc(row.modelData.after)
                        }
                    }
                    MouseArea {
                        id: rowArea
                        anchors.fill: parent
                        anchors.leftMargin: 32
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: editor.goToPage(row.modelData.page)
                    }
                }
            }
        }

        Row {
            visible: editor.searchResults.length > 0
            spacing: 8
            PillButton {
                text: editor.checkedCount === editor.searchResults.length ? "None" : "All"
                onClicked: editor.setAllResultsChecked(editor.checkedCount !== editor.searchResults.length)
            }
            PillButton {
                primary: true
                icon: "redact"
                text: "Redact " + editor.checkedCount + (editor.checkedCount === 1 ? " match" : " matches")
                enabled: editor.checkedCount > 0
                onClicked: editor.redactChecked()
            }
        }
        Item { width: 1; height: 2 }
    }

    // ---- marked areas ----
    SectionLabel { text: "Marked areas" }
    Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        width: parent.width
        wrapMode: Text.WordWrap
        color: editor.redactionCount ? Style.ink : Style.inkSoft
        font.pixelSize: Style.textSize
        text: editor.redactionCount === 0 ? "None yet"
              : editor.redactionCount + (editor.redactionCount === 1 ? " area" : " areas") + " will be blacked out"
    }
    Toggle {
        visible: editor.redactionCount > 0
        text: "Show as saved (solid black)"
        checked: editor.redactPreview
        onToggled: (on) => editor.setRedactPreview(on)
    }
    PillButton {
        visible: editor.redactionCount > 0
        text: "Remove all"
        onClicked: editor.clearRedactions()
    }

    Rectangle {
        width: parent.width
        height: note.implicitHeight + 20
        radius: Style.radiusSmall
        color: Style.field
        border.width: 1
        border.color: Style.divider
        Row {
            x: 10
            y: 10
            spacing: 8
            Icon { name: "info"; size: 16; color: Style.inkSoft }
            Text {
                textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
                id: note
                width: panel.width - 40 - 44
                text: editor.isPdf
                      ? "Redaction deletes the text and image parts under each box: they are gone from the saved copy, not just covered. That copy is also saved without any metadata."
                      : "Covered areas are filled solid black in the saved copy, which is saved without any metadata."
                color: Style.inkSoft
                font.pixelSize: Style.smallSize
                wrapMode: Text.WordWrap
            }
        }
    }
}
