import QtQuick
import QtQuick.Effects

// An image cropped to fill a rounded rectangle; fades in once loaded.
Item {
    id: root
    property alias source: img.source
    property alias status: img.status
    property real radius: 12
    property int sourceWidth: 1024
    Image {
        id: img; anchors.fill: parent; visible: false
        fillMode: Image.PreserveAspectCrop; asynchronous: true; cache: false
        sourceSize.width: root.sourceWidth
    }
    MultiEffect {
        anchors.fill: parent; source: img
        maskEnabled: true; maskSource: mask; maskThresholdMin: 0.5; maskSpreadAtMin: 1.0
        opacity: img.status === Image.Ready ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 500 } }
    }
    Item {
        id: mask; anchors.fill: parent; visible: false; layer.enabled: true; layer.smooth: true
        Rectangle { anchors.fill: parent; radius: root.radius; color: "black"; antialiasing: true }
    }
}
