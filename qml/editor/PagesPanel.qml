import QtQuick
import "."

// PDFs: turn pages, leave pages out.
PanelPage {
    id: panel

    tool: "edit"
    title: "Pages"
    subtitle: "Page " + (editor.page + 1) + " of " + editor.pageCount + ".  PgUp / PgDn to move between pages."

    SectionLabel { text: "Rotate" }
    Row {
        spacing: 6
        IconButton { icon: "rotate-ccw"; tip: "Rotate left  (Ctrl+Shift+R)"; onClicked: editor.rotate(-1) }
        IconButton { icon: "rotate-cw"; tip: "Rotate right  (Ctrl+R)"; onClicked: editor.rotate(1) }
    }
    Toggle {
        visible: editor.pageCount > 1
        text: "Rotate all pages"
        checked: editor.rotateAllPages
        onToggled: (on) => editor.setRotateAllPages(on)
    }

    Item { width: 1; height: 2 }
    SectionLabel { text: "Keep or remove" }
    PillButton {
        visible: !editor.pageDeleted
        danger: true
        icon: "trash"
        text: "Delete this page"
        enabled: editor.keptPages > 1
        onClicked: editor.deletePage()
    }
    PillButton {
        visible: editor.pageDeleted
        icon: "restore"
        text: "Restore this page"
        onClicked: editor.restorePage()
    }
    Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        text: editor.keptPages === editor.pageCount ? "All " + editor.pageCount + " pages are kept."
              : editor.keptPages + " of " + editor.pageCount + " pages will be kept."
        color: Style.inkSoft
        font.pixelSize: Style.smallSize
    }
}
