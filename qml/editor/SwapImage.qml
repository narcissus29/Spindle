import QtQuick
import "."

// An image whose source can change without flicker: the new picture loads
// (asynchronously, off the UI thread) behind the current one and fades in
// once it is ready. When sources change faster than they load, only the
// newest is loaded next, so a slider drag never queues up stale renders.
Item {
    id: sw

    property string source
    property int fadeMs: 140
    property bool mipmap: false

    readonly property bool ready: a.status === Image.Ready || b.status === Image.Ready
    property Image front: a
    readonly property Image back: front === a ? b : a
    property string pending: ""

    function load(src) {
        if (src === "" || src === String(front.source) && front.status === Image.Ready)
            return
        if (back.status === Image.Loading) {
            pending = src
            return
        }
        pending = ""
        back.source = src
    }

    function landed(img) {
        if (img !== back)
            return
        if (img.status === Image.Ready) {
            fade.stop()
            img.z = 2
            front.z = 1
            front = img
            fade.target = img
            fade.start()
        }
        if (img.status !== Image.Loading && pending !== "") {
            const next = pending
            pending = ""
            load(next)
        }
    }

    onSourceChanged: load(source)

    NumberAnimation {
        id: fade
        property: "opacity"
        from: 0
        to: 1
        duration: Style.d(sw.fadeMs)
        easing.type: Easing.OutCubic
        onFinished: sw.back.opacity = 0
    }

    Image {
        id: a
        anchors.fill: parent
        asynchronous: true
        cache: false
        smooth: true
        mipmap: sw.mipmap
        opacity: 0
        onStatusChanged: sw.landed(a)
    }
    Image {
        id: b
        anchors.fill: parent
        asynchronous: true
        cache: false
        smooth: true
        mipmap: sw.mipmap
        opacity: 0
        onStatusChanged: sw.landed(b)
    }

    Component.onCompleted: {
        // first picture: load straight into the back image, it fades in
        front = b
        load(source)
    }
}
