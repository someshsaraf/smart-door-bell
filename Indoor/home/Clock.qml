import QtQuick

// The time, ticking each second.
Item {
    id: c
    property date now: new Date()
    visible: false
    Timer { interval: 1000; running: true; repeat: true; onTriggered: c.now = new Date() }
}
