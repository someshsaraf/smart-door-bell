import QtQuick
import QtQuick.Effects

// Frosted glass: shows the part of `backdrop` (an already blurred copy of the wallpaper) that
// lies under the panel, tinted, with a hairline edge.
Item {
    id: f
    property Item backdrop
    property real radius: 28
    property color tint: Qt.rgba(1, 1, 1, 0.10)
    property color stroke: Qt.rgba(1, 1, 1, 0.16)
    property point at: Qt.point(0, 0)
    function place() { if (backdrop) at = mapToItem(backdrop, 0, 0) }
    onXChanged: place()
    onYChanged: place()
    onWidthChanged: place()
    onHeightChanged: place()
    Component.onCompleted: Qt.callLater(place)
    Timer { interval: 400; running: true; onTriggered: f.place() }  // after the layout has settled

    ShaderEffectSource {
        id: src; anchors.fill: parent; visible: false
        sourceItem: f.backdrop
        sourceRect: Qt.rect(f.at.x, f.at.y, f.width, f.height)
    }
    MultiEffect {
        anchors.fill: parent; source: src
        maskEnabled: true; maskSource: mask; maskThresholdMin: 0.5; maskSpreadAtMin: 1.0
    }
    Item {
        id: mask; anchors.fill: parent; visible: false; layer.enabled: true; layer.smooth: true
        Rectangle { anchors.fill: parent; radius: f.radius; color: "black"; antialiasing: true }
    }
    Rectangle {
        anchors.fill: parent; radius: f.radius; color: f.tint; antialiasing: true
        border.width: 1; border.color: f.stroke
    }
}
