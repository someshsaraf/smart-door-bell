import QtQuick

// Which story shows: turns every `interval` ms by itself; go(+1 / -1) turns by hand
// and starts the wait again. `progress` (0..1) runs towards the next turn.
Item {
    id: r
    property int count: 0
    property int index: 0
    property int interval: 12000
    property bool running: true
    property real progress: 0
    function go(d) {
        if (count < 2) return
        index = (index + d + count) % count
        anim.restart()
    }
    onCountChanged: if (index >= count) index = 0
    visible: false
    NumberAnimation {
        id: anim; target: r; property: "progress"; from: 0; to: 1; duration: r.interval
        running: r.running && r.count > 1
        onFinished: r.go(1)
    }
}
