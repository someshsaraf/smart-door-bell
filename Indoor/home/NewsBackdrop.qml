import QtQuick
import QtQuick.Effects

// The story's photo, heavily blurred and dimmed, cross-fading when the story changes.
Item {
    id: nb
    property string source: ""
    property real blur: 1.0
    property real brightness: -0.3
    property real saturation: 0.2
    property color fallback: "#10141c"
    property bool flip: false
    onSourceChanged: {
        if (flip) a.source = source
        else b.source = source
        flip = !flip
    }
    Rectangle { anchors.fill: parent; color: nb.fallback }
    Item {
        id: pics; anchors.fill: parent; visible: false
        Image {
            id: a; anchors.fill: parent; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 480
            opacity: !nb.flip && status === Image.Ready ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 1200 } }
        }
        Image {
            id: b; anchors.fill: parent; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 480
            opacity: nb.flip && status === Image.Ready ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 1200 } }
        }
    }
    MultiEffect {
        anchors.fill: parent; source: pics
        blurEnabled: true; blur: nb.blur; blurMax: 64; brightness: nb.brightness; saturation: nb.saturation
    }
}
