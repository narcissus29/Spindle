import QtQuick
import "../editor"

// Click, then press the keys you want. The shortcut is set as soon as a
// usable combination is pressed (setup.setShortcut); Esc cancels. It
// always shows setup.shortcut: what is saved and in use.
Rectangle {
    id: field

    property bool recording: false
    // "", "ok", "error". Starts as "error" if the saved shortcut doesn't
    // work (another app has it); setup.error says so.
    property string status: setup.shortcutProblem ? "error" : ""
    readonly property bool hasShortcut: setup.shortcut !== ""

    width: parent ? parent.width : 300
    height: 64
    radius: Style.radius
    color: recording ? Style.accentSoft : Style.field
    border.width: recording ? 2 : 1
    border.color: recording ? Style.accent : (status === "error" ? Style.danger : Style.panelBorder)
    Behavior on color { ColorAnimation { duration: Style.d(Style.fadeMs) } }
    Behavior on border.color { ColorAnimation { duration: Style.d(Style.fadeMs) } }

    function start() {
        status = ""
        recording = true
        setup.startCapture()
        catcher.forceActiveFocus()
    }
    function stop() {
        recording = false
        setup.endCapture()
    }

    function keyName(e) {
        const k = e.key
        if (k >= Qt.Key_A && k <= Qt.Key_Z) return String.fromCharCode(k)
        if (k >= Qt.Key_0 && k <= Qt.Key_9) return String.fromCharCode(k)
        if (k >= Qt.Key_F1 && k <= Qt.Key_F24) return "F" + (k - Qt.Key_F1 + 1)
        if (k === Qt.Key_Space) return "Space"
        return ""
    }

    Item {
        id: catcher
        anchors.fill: parent
        focus: field.recording
        Keys.onPressed: (e) => {
            e.accepted = true
            if (e.key === Qt.Key_Escape) { field.stop(); return }
            if ([Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta, Qt.Key_Super_L, Qt.Key_Super_R,
                 Qt.Key_AltGr].indexOf(e.key) >= 0) {
                live.text = setup.pretty(field.mods(e.modifiers).join("+")) + " + …"
                return
            }
            const key = field.keyName(e)
            const mods = field.mods(e.modifiers)
            if (key === "" || mods.length === 0 || (mods.length === 1 && mods[0] === "Shift")) {
                live.text = "Hold Ctrl, Alt or " + (setup.isWindows ? "Win" : "Super") + " and press a key"
                return
            }
            const text = mods.concat([key]).join("+")
            field.stop()
            field.status = setup.setShortcut(text) ? "ok" : "error"
        }
    }
    function mods(m) {
        const out = []
        if (m & Qt.ControlModifier) out.push("Ctrl")
        if (m & Qt.AltModifier) out.push("Alt")
        if (m & Qt.ShiftModifier) out.push("Shift")
        if (m & Qt.MetaModifier) out.push("Meta")
        return out
    }

    // what it shows
    KeyCaps {
        objectName: "shortcutKeys"
        anchors.left: parent.left
        anchors.leftMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        visible: !field.recording && field.hasShortcut
        keys: setup.shortcut
    }
    Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        id: live
        anchors.left: parent.left
        anchors.leftMargin: 18
        anchors.verticalCenter: parent.verticalCenter
        visible: field.recording || !field.hasShortcut
        text: field.recording ? "Press the keys you want…" : "Click here, then press your shortcut"
        color: field.recording ? Style.accent : Style.inkSoft
        font.pixelSize: Style.textSize + 1
        font.weight: Font.DemiBold
        onVisibleChanged: if (visible && field.recording) text = "Press the keys you want…"
    }
    Text {
        textFormat: Text.PlainText  // never rich text: no remote <img> from a file name or metadata
        anchors.right: parent.right
        anchors.rightMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        text: field.recording ? "Esc to cancel" : (field.hasShortcut ? "Change" : "")
        color: Style.inkSoft
        font.pixelSize: Style.smallSize
    }
    MouseArea {
        anchors.fill: parent
        enabled: !field.recording
        cursorShape: Qt.PointingHandCursor
        onClicked: field.start()
    }
}
