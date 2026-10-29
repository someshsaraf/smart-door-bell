import QtQuick

// Photos that slowly zoom and drift (Ken Burns) and cross-fade into the next one.
Item {
    id: show
    property var photos: []          // [{url, credit}]
    property int interval: 15000
    property int index: 0
    readonly property string credit: photos.length ? (photos[index % photos.length].credit || "") : ""
    clip: true

    function src(i) { return photos.length ? photos[(i + photos.length) % photos.length].url : "" }
    function go(d) {
        if (photos.length < 2) return
        index = (index + d + photos.length) % photos.length
        var next = a.shown ? b : a
        next.pending = true
        next.source = src(index)
        if (next.status === Image.Ready) swap(next)
        timer.restart()
    }
    function swap(layer) {
        var origins = [Item.TopLeft, Item.BottomRight, Item.Center, Item.Right, Item.Left, Item.Top]
        layer.pending = false
        layer.transformOrigin = origins[index % origins.length]
        layer.zoom.restart()
        layer.shown = true
        var other = layer === a ? b : a
        other.shown = false
    }
    onPhotosChanged: {
        index = 0
        a.pending = true
        a.source = src(0)
        if (a.status === Image.Ready) swap(a)
    }
    Timer { id: timer; interval: show.interval; running: show.visible && show.photos.length > 1; repeat: true; onTriggered: show.go(1) }

    component Layer: Image {
        id: img
        property bool shown: false
        property bool pending: false
        property alias zoom: zoomAnim
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop; asynchronous: true; cache: false
        sourceSize.width: 1920
        opacity: shown ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 1600; easing.type: Easing.InOutQuad } }
        onStatusChanged: if (status === Image.Ready && pending) show.swap(img)
        NumberAnimation { id: zoomAnim; target: img; property: "scale"; from: 1.02; to: 1.14; duration: show.interval + 4000 }
    }
    Layer { id: a }
    Layer { id: b }
}
